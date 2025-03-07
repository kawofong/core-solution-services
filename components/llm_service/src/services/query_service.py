# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Query Engine Service """

import functools
import gc
import json
import shutil
import tempfile
import time
import os
from typing import List, Optional, Generator, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from pathlib import Path
from common.utils.logging_handler import Logger
from common.models import (UserQuery, QueryResult,
                          QueryEngine, QueryDocument,
                          QueryReference,
                          QueryDocumentChunk,
                          BatchJobModel)
from common.utils.errors import (ResourceNotFoundException,
                                 ValidationError)
from common.utils.http_exceptions import InternalServerError
from utils.errors import NoDocumentsIndexedException
from google.cloud import aiplatform, storage
from google.cloud.exceptions import Conflict
from vertexai.preview.language_models import TextEmbeddingModel
from langchain.text_splitter import CharacterTextSplitter
from langchain.document_loaders import CSVLoader
from pypdf import PdfReader
from services import llm_generate
from services import query_prompts

from config import (PROJECT_ID, DEFAULT_QUERY_CHAT_MODEL,
                    DEFAULT_QUERY_EMBEDDING_MODEL, GOOGLE_LLM, REGION)

# number of text chunks to process into an embeddings file
MAX_NUM_TEXT_CHUNK_PROCESS = 1000

# number of document match results to retrieve
NUM_MATCH_RESULTS = 5

# text chunk size for embedding data
CHUNK_SIZE = 1000

# Create a rate limit of 300 requests per minute.
API_CALLS_PER_SECOND = 300 / 60

# According to the docs, each request can process 5 instances per request
ITEMS_PER_REQUEST = 5

# embedding dimensions generated by TextEmbeddingModel
DIMENSIONS = 768

async def query_generate(
            user_id: str,
            prompt: str,
            q_engine: QueryEngine,
            llm_type: Optional[str] = DEFAULT_QUERY_CHAT_MODEL,
            user_query: Optional[UserQuery] = None) -> \
                Tuple[QueryResult, List[QueryReference]]:
  """
  Execute a query over a query engine

  Args:
    prompt: the text prompt to pass to the query engine

    query_engine: the name of the query engine to use

    llm_type (optional): chat model to use for query

    user_query (optional): an existing user query for context

  Returns:
    QueryResult: the query result object

  Raises:
    ResourceNotFoundException if the named query engine doesn't exist
  """
  # get doc context for question
  query_references = await _query_doc_matches(q_engine, prompt)

  # generate question prompt for chat model
  question_prompt = query_prompts.question_prompt(prompt, query_references)

  # send question prompt to model
  question_response = await llm_generate.llm_chat(question_prompt, llm_type)

  # save query result
  query_ref_ids = []
  for ref in query_references:
    query_reference = QueryReference(
      query_engine_id = q_engine.id,
      query_engine=q_engine.name,
      document_id = ref["document_id"],
      chunk_id = ref["chunk_id"]
    )
    query_reference.save()
    query_ref_ids.append(query_reference.id)

  query_result = QueryResult(query_engine_id=q_engine.id,
                             query_engine=q_engine.name,
                             query_refs=query_ref_ids,
                             response=question_response)
  query_result.save()

  # save user query history
  if user_query is None:
    user_query = UserQuery(user_id=user_id,
                           query_engine_id=q_engine.id)
    user_query.save()
  user_query.update_history(prompt, question_response, query_references)

  return query_result, query_references


async def _query_doc_matches(q_engine: QueryEngine,
                             query_prompt: str) -> List[dict]:
  """
  For a query prompt, retrieve text chunks with doc references
  from matching documents.
  """
  # generate embeddings for prompt
  query_embeddings = _encode_texts_to_embeddings([query_prompt])

  # retrieve text matches for query
  index_endpoint = aiplatform.MatchingEngineIndexEndpoint(q_engine.endpoint)

  match_indexes_list = index_endpoint.find_neighbors(
      queries=query_embeddings,
      deployed_index_id=q_engine.deployed_index_name,
      num_neighbors=NUM_MATCH_RESULTS
  )

  # assemble document chunk matches from match indexes
  query_references = []
  match_indexes = match_indexes_list[0]
  for match in match_indexes:
    doc_chunk = QueryDocumentChunk.find_by_index(q_engine.id, int(match.id))
    if doc_chunk is None:
      raise ResourceNotFoundException(
        f"Missing doc chunk match index {match.id} q_engine {q_engine.name}")
    query_doc = QueryDocument.find_by_id(doc_chunk.query_document_id)
    if query_doc is None:
      raise ResourceNotFoundException(
        f"Query doc {doc_chunk.query_document_id} q_engine {q_engine.name}")
    query_ref = {
      "document_id": query_doc.id,
      "document_url": query_doc.doc_url,
      "document_text": doc_chunk.text,
      "chunk_id": doc_chunk.id
    }
    query_references.append(query_ref)

  return query_references

def batch_build_query_engine(request_body: Dict, job: BatchJobModel) -> Dict:
  """
  Handle a batch job request for query engine build.

  Args:
    request_body: dict of query engine build params
    job: BatchJobModel model object
  Returns:
    dict containing job meta data
  """
  doc_url = request_body.get("doc_url")
  query_engine = request_body.get("query_engine")
  user_id = request_body.get("user_id")
  is_public = request_body.get("is_public")
  llm_type = request_body.get("llm_type")

  Logger.info(f"Starting batch job for {query_engine} job id {job.id}")

  q_engine, docs_processed, docs_not_processed = \
      query_engine_build(doc_url, query_engine, user_id, is_public, llm_type)

  # update result data in batch job model
  docs_processed_urls = [doc.doc_url for doc in docs_processed]
  result_data = {
    "query_engine_id": q_engine.id,
    "docs_processed": docs_processed_urls,
    "docs_not_processed": docs_not_processed
  }
  job.result_data = result_data
  job.save(merge=True)

  Logger.info(f"Completed batch job query engine build for {query_engine}")

  return result_data

def query_engine_build(doc_url: str, query_engine: str, user_id: str,
                       is_public: Optional[bool] = True,
                       llm_type: Optional[str] = "") -> \
                       Tuple[str, List[QueryDocument], List[str]]:
  """
  Build a new query engine. NOTE currently supports only Vertex
   TextEmbeddingModel for embeddings.

  Args:
    doc_url: the URL to the set of documents to be indexed

    query_engine: the name of the query engine to create

    user_id: user id of engine creator

    is_public: is query engine publically usable?

    llm_type: LLM used for query embeddings (currently not used)

  Returns:
    Tuple of QueryEngine id, list of QueryDocument objects of docs processed,
      list of urls of docs not processed

  Raises:
    ValidationError if the named query engine already exists
  """
  q_engine = QueryEngine.find_by_name(query_engine)
  if q_engine is not None:
    raise ValidationError(f"Query engine {query_engine} already exists")

  # create model
  llm_type = DEFAULT_QUERY_EMBEDDING_MODEL
  q_engine = QueryEngine(name=query_engine,
                         created_by=user_id,
                         llm_type=llm_type,
                         is_public=is_public)
  q_engine.save()

  # build document index
  try:
    docs_processed, docs_not_processed = build_doc_index(doc_url, query_engine)
  except Exception as e:
    # delete query engine model if build unsuccessful
    QueryDocument.collection.filter(
      "query_engine_id", "==", q_engine.id
    ).delete()
    QueryDocumentChunk.collection.filter(
      "query_engine_id", "==", q_engine.id
    ).delete()
    QueryEngine.delete_by_id(q_engine.id)
    raise InternalServerError(e) from e

  Logger.info(f"Completed query engine build for {query_engine}")

  return q_engine, docs_processed, docs_not_processed


def build_doc_index(doc_url:str, query_engine: str) -> \
        Tuple[List[QueryDocument], List[str]]:
  """
  Build the document index.
  Supports only GCS URLs initially, containing PDF files.

  Args:
    doc_url: URL pointing to folder of documents
    query_engine: the query engine to

  Returns:
    Tuple of list of QueryDocument objects of docs processed,
      list of urls of docs not processed
  """
  q_engine = QueryEngine.find_by_name(query_engine)
  if q_engine is None:
    raise ResourceNotFoundException(f"cant find query engine {query_engine}")

  try:
    storage_client = storage.Client(project=PROJECT_ID)

    # create bucket for ME index data
    bucket_name = f"{PROJECT_ID}-{query_engine}-data"
    try:
      bucket = storage_client.create_bucket(bucket_name, location=REGION)
    except Conflict:
      # if bucket already exists, delete and recreate
      bucket = storage_client.bucket(bucket_name)
      bucket.delete(force=True)
      bucket = storage_client.create_bucket(bucket_name, location=REGION)
    bucket_uri = f"gs://{bucket.name}"

    # process docs at url and upload embeddings to GCS for indexing
    docs_processed, docs_not_processed = _process_documents(doc_url,
                                            bucket_name,
                                            q_engine, storage_client)

    # make sure we actually processed some docs
    if len(docs_processed) == 0:
      raise NoDocumentsIndexedException(
          f"Failed to process any documents at url {doc_url}")

    # ME index name and description
    index_name = query_engine.replace("-", "_") + "_MEindex"

    # create ME index and endpoint
    _create_me_index_and_endpoint(index_name, bucket_uri, q_engine)

    return docs_processed, docs_not_processed

  except Exception as e:
    Logger.error(f"Error creating doc index {e}")
    raise InternalServerError(str(e)) from e


def _create_me_index_and_endpoint(index_name: str, bucket_uri: str,
                                  q_engine: QueryEngine):
  """ Create matching engine index and endpoint """
  # create ME index
  Logger.info(f"creating matching engine index {index_name}")

  index_description = \
    "Matching Engine index for LLM Service query engine: " + q_engine.name

  tree_ah_index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
      display_name=index_name,
      contents_delta_uri=bucket_uri,
      dimensions=DIMENSIONS,
      approximate_neighbors_count=150,
      distance_measure_type="DOT_PRODUCT_DISTANCE",
      leaf_node_embedding_count=500,
      leaf_nodes_to_search_percent=80,
      description=index_description,
  )
  Logger.info(f"Created matching engine index {index_name}")

  # create index endpoint
  index_endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
      display_name=index_name,
      description=index_name,
      public_endpoint_enabled=True,
  )
  Logger.info(f"Created matching engine endpoint for {index_name}")

  # store index in query engine model
  q_engine.index_id = tree_ah_index.resource_name
  q_engine.index_name = index_name
  q_engine.endpoint = index_endpoint.resource_name
  q_engine.update()

  # deploy index endpoint
  try:
    # this seems to consistently time out, throwing an error, but
    # actually sucessfully deploys the endpoint
    index_endpoint.deploy_index(
        index=tree_ah_index, deployed_index_id=q_engine.deployed_index_name
    )
    Logger.info(f"Deployed matching engine endpoint for {index_name}")
  except Exception as e:
    Logger.error(f"Error creating ME index or endpoint {e}")


def _process_documents(doc_url: str, bucket_name: str,
                       q_engine: QueryEngine, storage_client) -> \
                       Tuple[List[QueryDocument], List[str]]:
  """
  Process docs at url and upload embeddings to GCS for indexing.
  Returns:
     Tuple of list of QueryDocument objects for docs processed,
        list of doc urls of docs not processed
  """
  with tempfile.TemporaryDirectory() as temp_dir:
    # download files to local directory
    doc_filepaths = _download_files_to_local(storage_client, temp_dir, doc_url)

    if len(doc_filepaths) == 0:
      raise NoDocumentsIndexedException(
          f"No documents can be indexed at url {doc_url}")

    # use langchain text splitter
    text_splitter = CharacterTextSplitter(chunk_size=CHUNK_SIZE,
                                          chunk_overlap=0)

    # counter for unique index ids
    index_base = 0

    # add embeddings for each doc to index data stored in bucket
    docs_processed = []
    docs_not_processed = []
    for doc in doc_filepaths:
      doc_name, doc_url, doc_filepath = doc
      Logger.info(f"generating index data for {doc_name}")

      # read doc data and split into text chunks
      # skip any file that can't be read or generates an error
      try:
        doc_text_list = _read_doc(doc_name, doc_filepath)
        if doc_text_list is None:
          Logger.error(f"no content read from {doc_name}")
          docs_not_processed.append(doc_url)
          continue
      except Exception as e:
        Logger.error(f"error reading doc {doc_name}: {e}")
        docs_not_processed.append(doc_url)
        continue

      # split text into chunks
      text_chunks = []
      for text in doc_text_list:
        text_chunks.extend(text_splitter.split_text(text))

      # generate embedding data and store in local dir
      new_index_base, embeddings_dir = \
          _generate_index_data(doc_name, text_chunks, index_base)

      # copy data files up to bucket
      bucket = storage_client.get_bucket(bucket_name)
      for root, _, files in os.walk(embeddings_dir):
        for filename in files:
          local_path = os.path.join(root, filename)
          blob = bucket.blob(filename)
          blob.upload_from_filename(local_path)

      Logger.info(f"data uploaded for {doc_name}")

      # clean up tmp files
      shutil.rmtree(embeddings_dir)
      os.remove(doc_filepath)

      # store QueryDocument and QueryDocumentChunk models
      query_doc = QueryDocument(query_engine_id = q_engine.id,
                                query_engine = q_engine.name,
                                doc_url = doc_url,
                                index_start = index_base,
                                index_end = new_index_base)
      query_doc.save()

      for i in range(0, len(text_chunks)):
        query_doc_chunk = QueryDocumentChunk(
                                  query_engine_id = q_engine.id,
                                  query_document_id = query_doc.id,
                                  index = i + index_base,
                                  text = text_chunks[i])
        query_doc_chunk.save()

      index_base = new_index_base

      docs_processed.append(query_doc)

  return docs_processed, docs_not_processed


def _download_files_to_local(storage_client, local_dir, doc_url: str) -> \
    List[Tuple[str, str, str]]:
  """ Download files from GCS to a local tmp directory """
  docs = []
  bucket_name = doc_url.split("gs://")[1].split("/")[0]
  for blob in storage_client.list_blobs(bucket_name):
    # Download the file to the tmp folder flattening all directories
    file_name = Path(blob.name).name
    file_path = os.path.join(local_dir, file_name)
    blob.download_to_filename(file_path)
    docs.append((blob.name, blob.path, file_path))
  return docs


def _read_doc(doc_name:str, doc_filepath: str) -> List[str]:
  """ Read document and return content as a list of strings """
  doc_extension = doc_name.split(".")[-1]
  doc_extension = doc_extension.lower()
  doc_text_list = None
  loader = None

  if doc_extension == "txt":
    with open(doc_filepath, "r", encoding="utf-8") as f:
      doc_text = f.read()
    doc_text_list = [doc_text]
  elif doc_extension == "csv":
    loader = CSVLoader(file_path=doc_filepath)
  elif doc_extension == "pdf":
    # read PDF into array of pages
    doc_text_list = []
    with open(doc_filepath, "rb") as f:
      reader = PdfReader(f)
      num_pages = len(reader.pages)
      Logger.info(f"Reading pdf file {doc_name} with {num_pages} pages")
      for page in range(num_pages):
        doc_text_list.append(reader.pages[page].extract_text())
      Logger.info(f"Finished reading pdf file {doc_name}")
  else:
    # return None if doc type not supported
    Logger.error(
        f"Cannot read {doc_name}: unsupported extension {doc_extension}")
    pass

  if loader is not None:
    langchain_document = loader.load()
    doc_text_list = [section.content for section in langchain_document]

  return doc_text_list

def _encode_texts_to_embeddings(
    sentence_list: List[str]) -> List[Optional[List[float]]]:
  """ encode text using Vertex AI embedding model """
  model = TextEmbeddingModel.from_pretrained(
      GOOGLE_LLM.get(DEFAULT_QUERY_EMBEDDING_MODEL))
  try:
    embeddings = model.get_embeddings(sentence_list)
    return [embedding.values for embedding in embeddings]
  except Exception:
    return [None for _ in range(len(sentence_list))]


# Generator function to yield batches of text_chunks
def _generate_batches(text_chunks: List[str], batch_size: int
    ) -> Generator[List[str], None, None]:
  """ generate batches of text_chunks """
  for i in range(0, len(text_chunks), batch_size):
    yield text_chunks[i : i + batch_size]


def _get_embedding_batched(
    text_chunks: List[str], api_calls_per_second: int = 10, batch_size: int = 5
) -> Tuple[List[bool], np.ndarray]:
  """ get embbedings for a list of text strings """

  embeddings_list: List[List[float]] = []

  # Prepare the batches using a generator
  batches = _generate_batches(text_chunks, batch_size)

  seconds_per_job = 1 / api_calls_per_second

  with ThreadPoolExecutor() as executor:
    futures = []
    for batch in batches:
      futures.append(
          executor.submit(functools.partial(_encode_texts_to_embeddings), batch)
      )
      time.sleep(seconds_per_job)

    for future in futures:
      embeddings_list.extend(future.result())

  is_successful = [
      embedding is not None for sentence, embedding in zip(
        text_chunks, embeddings_list)
  ]
  embeddings_list_successful = np.stack(
    [embedding for embedding in embeddings_list if embedding is not None]
  )
  return is_successful, embeddings_list_successful


def _generate_index_data(doc_name: str, text_chunks: List[str],
                         index_base: int) -> Tuple[int, str]:
  """ generate matching engine index data files in a local directory """

  chunk_index = 0
  num_chunks = len(text_chunks)

  # create a list of chunks to process
  while chunk_index < num_chunks:
    remaining_chunks = num_chunks - chunk_index
    chunk_size = min(MAX_NUM_TEXT_CHUNK_PROCESS, remaining_chunks)
    end_chunk_index = chunk_index + chunk_size
    process_chunks = text_chunks[chunk_index:end_chunk_index]

    Logger.info(f"processing {chunk_size} chunks for file {doc_name} " \
        f"remaining chunks {remaining_chunks}")

    # generate an np array of chunk IDs starting from index base
    ids = np.arange(index_base, index_base + len(process_chunks))

    # Create temporary folder to write embeddings to
    embeddings_dir = Path(tempfile.mkdtemp())

    # Convert chunks to embeddings in batches, to manage API throttling
    is_successful, chunk_embeddings = _get_embedding_batched(
        text_chunks=process_chunks,
        api_calls_per_second=API_CALLS_PER_SECOND,
        batch_size=ITEMS_PER_REQUEST,
    )

    Logger.info(f"generated embeddings for chunks" \
        f" {chunk_index} to {end_chunk_index}")

    # create JSON
    embeddings_formatted = [
      json.dumps(
        {
          "id": str(idx),
          "embedding": [str(value) for value in embedding],
        }
      )
      + "\n"
      for idx, embedding in zip(ids[is_successful], chunk_embeddings)
    ]

    # Create output file
    doc_stem = Path(doc_name).stem
    chunk_path = embeddings_dir.joinpath(
        f"{doc_stem}_{index_base}_index.json")

    # write embeddings for chunk to file
    with open(chunk_path, "w", encoding="utf-8") as f:
      f.writelines(embeddings_formatted)

    Logger.info(f"wrote embeddings file for chunks {chunk_index} " \
        f"to {end_chunk_index}")

    # clean up any large data structures
    gc.collect()

    index_base = index_base + len(process_chunks)
    chunk_index = chunk_index + len(process_chunks)

  return index_base, embeddings_dir
