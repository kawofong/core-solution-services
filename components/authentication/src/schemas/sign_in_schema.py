"""
Copyright 2023 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

"""
Pydantic Model for Sign In API's
"""
from typing import Optional
from pydantic import BaseModel
from schemas.schema_examples import (
    SIGN_IN_WITH_CREDENTIALS_API_INPUT_EXAMPLE,
    SIGN_IN_WITH_CREDENTIALS_API_RESPONSE_EXAMPLE,
    SIGN_IN_WITH_TOKEN_RESPONSE_EXAMPLE)

# pylint: disable=invalid-name
class SignInWithCredentialsModel(BaseModel):
  """Sign In with Credentials Input Pydantic Model"""
  email: str
  password: str

  class Config():
    orm_mode = True
    schema_extra = {"example": SIGN_IN_WITH_CREDENTIALS_API_INPUT_EXAMPLE}
    extra = "forbid"


class IDPSignInWithCredentialsResponseModel(BaseModel):
  """Sign In With Credentials Response Pydantic Model"""
  user_id: str
  kind: str
  localId: str
  email: str
  displayName: str
  idToken: str
  registered: bool
  refreshToken: str
  expiresIn: str
  session_id: str


class SignInWithCredentialsResponseModel(BaseModel):
  """Sign In With Credentials Response Pydantic Model"""
  success: Optional[bool] = True
  message: Optional[str] = "Successfully signed in"
  data: IDPSignInWithCredentialsResponseModel

  class Config():
    orm_mode = True
    schema_extra = {
        "example": {
            "success": True,
            "message": "Successfully signed in",
            "data": SIGN_IN_WITH_CREDENTIALS_API_RESPONSE_EXAMPLE
        }
    }


class IDPSignInWithTokenResponse(BaseModel):
  """Sign In With Token Response Pydantic Model"""
  user_id: str
  federatedId: str
  providerId: str
  email: str
  emailVerified: bool
  firstName: str
  fullName: str
  lastName: str
  photoUrl: str
  localId: str
  displayName: str
  idToken: str
  refreshToken: str
  expiresIn: str
  oauthIdToken: str
  rawUserInfo: str
  kind: str
  session_id: str


class SignInWithTokenResponseModel(BaseModel):
  """SignIn With Token Response Pydantic Model"""
  success: Optional[bool] = True
  message: Optional[str] = "Successfully signed in"
  data: IDPSignInWithTokenResponse

  class Config():
    orm_mode = True
    schema_extra = {
        "example": {
            "success": True,
            "message": "Successfully signed in",
            "data": SIGN_IN_WITH_TOKEN_RESPONSE_EXAMPLE
        }
    }
