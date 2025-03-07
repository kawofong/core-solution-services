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

"""FireO model for batch jobs"""

from enum import Enum
from fireo.fields import TextField, MapField, IDField
from common.models import GCSPathField
from common.models import BaseModel

class JobStatus(Enum):
  """ Enum class for JobStatus """
  JOB_STATUS_PENDING = "pending"
  JOB_STATUS_ACTIVE = "active"
  JOB_STATUS_SUCCEEDED = "succeeded"
  JOB_STATUS_FAILED = "failed"
  JOB_STATUS_ABORTED = "aborted"


class BatchJobModel(BaseModel):
  """Model class for batch job"""
  id = IDField()
  name = TextField(required=True, default="")
  input_data = TextField()
  type = TextField(required=True)
  status = TextField(required=True)
  message = TextField(required=True, default="")
  generated_item_id = TextField()
  output_gcs_path = GCSPathField()
  errors = MapField(default={})
  job_logs = MapField(default={})
  metadata = MapField(default={})
  result_data = MapField(default={})
  uuid = TextField()

  class Meta:
    ignore_none_field = False
    collection_name = BaseModel.DATABASE_PREFIX+"batch_jobs"

  @classmethod
  def find_by_name(cls, name):
    job = cls.collection.filter("name", "==", name).get()
    return job

  @classmethod
  def find_by_uuid(cls, name):
    job = cls.collection.filter("uuid", "==", name).get()
    return job

  @classmethod
  def find_by_job_type(cls, job_type):
    jobs = cls.collection.filter("type", "==", job_type).fetch()
    return jobs
