/**
 * Copyright 2023 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 */

resource "google_storage_bucket" "llm_doc_storage" {
  project                     = var.project_id
  name                        = "${var.project_id}-llm-docs"
  location                    = "US"
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = true
}

# Upload an sample PDF to the newly created bucket.
resource "google_storage_bucket_object" "default" {
  depends_on = [ google_storage_bucket.llm_doc_storage ]

  name         = "genai-sample-doc.pdf"
  source       = "genai-sample-doc.pdf"
  content_type = "application/pdf"
  bucket       = google_storage_bucket.llm_doc_storage.id
}

resource "google_firestore_index" "user_chats_index" {
  project = var.project_id
  collection = "user_chats"

  fields {
    field_path = "deleted_at_timestamp"
    order      = "ASCENDING"
  }
  fields {
    field_path = "user_id"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_time"
    order      = "DESCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "batch_jobs_index" {
  project = var.project_id
  collection = "batch_jobs"

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "type"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_time"
    order      = "ASCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "ASCENDING"
  }
}
