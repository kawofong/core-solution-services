# Large Language Module Service

## Setup

Set API Keys to environment variables:
```
export OPENAI_API_KEY="<Your API key>"
export COHERE_API_KEY="<Your API key>"
```

Run the following to update API Keys to Cloud Secret.
```
gcloud secrets create "openai-api-key"
gcloud secrets create "cohere-api-key"
echo $OPENAI_API_KEY | gcloud secrets versions add "openai-api-key" --data-file=-
echo $COHERE_API_KEY | gcloud secrets versions add "cohere-api-key" --data-file=-
```

## Apply terraform infra for LLM service

Set up Cloud Storage with one sample PDF file for Query Engine to use later:
```
sb infra apply 3-llm
```
- This will create a `$PROJECT_ID-llm-docs` bucket and upload a `llm-sample-doc.pdf`.
- It will add required Firestore indexes.

## After Deployment

### Create a Query Engine

Get the access token for a particular user:
```
# Setting BASE_URL Without trailing slash.
BASE_URL=https://your.domain.com
PYTHONPATH=components/common/src/ python components/authentication/scripts/user_tool.py get_token --base-url=$BASE_URL
```
- This will print out the token in the terminal.

Run the following to build a Query engine:
```
ID_TOKEN=<the token printed above>
QUERY_ENGINE_NAME="qe1"
curl --location "$BASE_URL/llm-service/api/v1/query/engine" \
--header "Content-Type: application/json" \
--header "Authorization: Bearer $ID_TOKEN" \
--data "{
    \"doc_url\": \"gs://$PROJECT_ID-llm-docs/genai-sample-doc.pdf\",
    \"query_engine\": \"$QUERY_ENGINE_NAME\",
    \"llm_type\": \"VertexAI-Chat\",
    \"is_public\": true
}"
```

This will create a Vertex AI Matching Engine Index. You can check out the progress on https://console.cloud.google.com/vertex-ai/matching-engine/indexes?referrer=search&project=$PROJECT_ID.
> Note: It may take 15+ minutes to create a Matching Engine Index.
> The Kubernetes Job may show time out while creating the Matching Engine and Endpoint in its logs, but the creation process will still be executed in the background.
> You will see the Endpoint created soon later.

Once finished, you shall see the folloing artifacts:
- A record in `query_engines` collection in Firestore, representing the new Query engine.
- A corresponding document metadata in `query_documents` collection in Firestore.
- A record in `query_document_chunk` collection in Firestore.
- A Vertex AI Matching Engine.

## Troubleshoot

### Deploy the microservice with live logs output in local terminal

To run a livereload service in the remote cluster and print logs in the local terminal:
```
sb deploy --component=llm_service --dev
```
- This will deploy the LLM service to the remote main cluster, and set up port forwarding with live reload from local source code.
- You can monitor all API requests and responses in the terminal output.

Once deployed, it will print logs from the microservice, e.g.
```
[llm-service] INFO:     Will watch for changes in these directories: ['/opt']
[llm-service] INFO:     Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
[llm-service] INFO:     Started reloader process [1] using StatReload
[llm-service] INFO:     Started server process [8]
[llm-service] INFO:     Waiting for application startup.
[llm-service] INFO:     Application startup complete.
[llm-service] INFO:     35.191.8.94:32768 - "GET /ping HTTP/1.1" 200 OK
[llm-service] INFO:     35.191.8.64:32768 - "GET /ping HTTP/1.1" 200 OK
[llm-service] INFO:     35.191.8.66:44092 - "GET /ping HTTP/1.1" 200 OK
[llm-service] INFO:     10.1.1.1:55346 - "GET /ping HTTP/1.1" 200 OK
[llm-service] INFO:     10.1.1.1:55348 - "GET /ping HTTP/1.1" 200 OK
```

### Troubleshooting LLM Service - building a query engine

#### Montior the batch job in Kubernetes Workloads

Once sending the API call to https://$YOUR_DOMAIN/llm-service/api/v1/query/engine, it will create a Kubernetes Job and a corresponding Firestore record in `batch_jobs` collections.
- Check the batch_job object in https://console.cloud.google.com/firestore/databases/-default-/data/panel/batch_jobs
- Check the Kubernetes Job in the Kubernetes Workload: https://console.cloud.google.com/kubernetes/workload/overview

In the Kubernetes Workload view, you'll see workloads with "Job" type.
- If the job is created and running succesfully, the status shall be "OK" or "Running".
- If you are seeing the status as "Error" or something else like "BackoffLimitExceeded", this means the Job failed.

Run the following to describe the job in the terminal:
```
kubectl describe job atestjob-1eab-4f55-9075-895ed6e86c24
```
- You'd see something like:
  ```
  Events:
  Type     Reason                Age   From            Message
  ----     ------                ----  ----            -------
  Normal   SuccessfulCreate      47m   job-controller  Created pod: atestjob-1eab-4f55-9075-895ed6e86c24-dtdlh
  Warning  BackoffLimitExceeded  47m   job-controller  Job has reached the specified backoff limit
  ```

Run the following to triage the logs from the failed pod:
```
kubectl logs atestjob-1eab-4f55-9075-895ed6e86c24-dtdlh
```

For example, it would print logs with error messages like below:
```
Traceback (most recent call last):
  File "/opt/run_batch_job.py", line 62, in <module>
    app.run(main)
  File "/usr/local/lib/python3.9/site-packages/absl/app.py", line 308, in run
    _run_main(main, args)
  File "/usr/local/lib/python3.9/site-packages/absl/app.py", line 254, in _run_main
    sys.exit(main(argv))
  File "/opt/run_batch_job.py", line 57, in main
    raise e
  File "/opt/run_batch_job.py", line 43, in main
    _ = batch_build_query_engine(request_body, job)
  File "/opt/services/query_service.py", line 189, in batch_build_query_engine
    query_engine_build(doc_url, query_engine, user_id, is_public, llm_type)
  File "/opt/services/query_service.py", line 255, in query_engine_build
    raise InternalServerError(e) from e
common.utils.http_exceptions.InternalServerError: 403 GET https://storage.googleapis.com/storage/v1/b/query-engine-test-me-data/o?maxResults=257&projection=noAcl&prettyPrint=false: gke-sa@test-project.iam.gserviceaccount.com does not have storage.objects.list access to the Google Cloud Storage bucket. Permission 'storage.objects.list' denied on resource (or it may not exist).
```
- In this example, it appeared to be the IAM permissions problem for the `gke-sa` service account.


#### Received 403 error in LLM service

When sending the API call to https://$YOUR_DOMAIN/llm-service/api/v1/query/engine but received a 403 error. It could be one of the following reasons:

- The Kubenetes Role and Role Binding are not set correctly.
  - Check out the `components/llm_service/kustomize/base` folder, you will see role.yaml and role_binding.yaml. Make sure they exist.
  - Check the `kustomization.yaml` file and make sure the role.yaml and role_binding.yaml are in `resources` list. Orders don't matter.
  - Check out `role_binding.yaml` and ensure the Service Account name is exact `gke-sa`. This is defined in the `/terraform/stages/2-gke/main.tf`

#### Batch job created but failed.

If a batch job is created succesfully, but there's an error about creating a pod, run the following to triage kubernetes resources:

```
$ kubectl get jobs
NAME                                   COMPLETIONS   DURATION   AGE
d49bb762-4c0e-4972-abf9-5d284bd74597   0/1           3m57s      3m57s

$ kubectl describe job d49bb762-4c0e-4972-abf9-5d284bd74597

Pod Template:
  Labels:           batch.kubernetes.io/controller-uid=4107c701-3461-489a-8bc3-f52cb48a39e5
                    batch.kubernetes.io/job-name=d49bb762-4c0e-4972-abf9-5d284bd74597
                    controller-uid=4107c701-3461-489a-8bc3-f52cb48a39e5
                    job-name=d49bb762-4c0e-4972-abf9-5d284bd74597
  Service Account:  gke-sa
  Containers:
   jobcontainer:
    Image:      gcr.io/$PROJECT_ID/llm-service:1fd3ca9-dirty
    Port:       <none>
    Host Port:  <none>
    Command:
      python
      run_batch_job.py
    Args:
      --container_name
      d49bb762-4c0e-4972-abf9-5d284bd74597
    Limits:
      cpu:     3
      memory:  7000Mi
    Requests:
      cpu:     2
      memory:  5000Mi
    Environment:
      DATABASE_PREFIX:
      PROJECT_ID:         $PROJECT_ID
      ENABLE_OPENAI_LLM:  True
      ENABLE_COHERE_LLM:  True
      GCP_PROJECT:        $PROJECT_ID
    Mounts:               <none>
  Volumes:                <none>
Events:
  Type     Reason                Age    From            Message
  ----     ------                ----   ----            -------
  Normal   SuccessfulCreate      4m17s  job-controller  Created pod: d49bb762-4c0e-4972-abf9-5d284bd74597-l87wf
  Warning  BackoffLimitExceeded  4m8s   job-controller  Job has reached the specified backoff limit
```

Then describe the pod and see what's going on.
```
$ kubectl describe pod d49bb762-4c0e-4972-abf9-5d284bd74597-l87wf

...
Containers:
  jobcontainer:
    Container ID:  containerd://60eb1dde2b50c80515b0a0b6ff717beb970add98f9e3529f2bc34cb868159772
    Image:         gcr.io/$PROJECT_ID/llm-service:1fd3ca9-dirty
    Image ID:      gcr.io/$PROJECT_ID/llm-service@sha256:4b243b37d0457f2464161015b23dad48fe50937b3d509f627ac22668035319a5
    Port:          <none>
    Host Port:     <none>
    Command:
      python
      run_batch_job.py
    Args:
      --container_name
      d49bb762-4c0e-4972-abf9-5d284bd74597
    State:          Terminated
      Reason:       Error
      Exit Code:    1
      Started:      Mon, 14 Aug 2023 14:15:24 -0400
      Finished:     Mon, 14 Aug 2023 14:15:24 -0400
```

Now the pod seems get some error, run the following to checkout logs (Or see logs in Stackdriver.)
```
kubectl logs d49bb762-4c0e-4972-abf9-5d284bd74597-l87wf
```

