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

"""Class and methods for handling validate route."""

from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer
from firebase_admin.auth import InvalidIdTokenError, ExpiredIdTokenError
from common.utils.errors import TokenNotFoundError, UnauthorizedUserError
from common.utils.http_exceptions import (BadRequest, InvalidToken,
                                          InternalServerError, Unauthorized)
from services.validate_token_service import validate_token
from schemas.validate_token_schema import ValidateTokenResponseModel
from config import ERROR_RESPONSES

router = APIRouter(
    tags=["Token Validation"],
    responses=ERROR_RESPONSES)
auth_scheme = HTTPBearer(auto_error=False)


@router.get(
    "/validate",
    response_model=ValidateTokenResponseModel,
    response_model_exclude_none=True)
def validate_id_token(token: auth_scheme = Depends()):
  """Validates the Token present in Headers
  ### Raises:
  UnauthorizedUserError:
    If user does not exist in firestore <br/>
  InvalidTokenError:
    If the token is invalid or has expired <br/>
  Exception 500:
    Internal Server Error. Raised if something went wrong
  ### Returns:
      ValidateTokenResponseModel: Details related to the token
  """

  try:
    if token is None:
      raise TokenNotFoundError("Token not found")
    token_dict = dict(token)
    return {
        "success": True,
        "message": "Token validated successfully",
        "data": validate_token(token_dict["credentials"])
    }
  except UnauthorizedUserError as e:
    raise Unauthorized(str(e)) from e
  except TokenNotFoundError as e:
    raise BadRequest(str(e)) from e
  except (InvalidIdTokenError, ExpiredIdTokenError) as err:
    raise InvalidToken(str(err)) from err
  except Exception as e:
    raise InternalServerError(str(e)) from e
