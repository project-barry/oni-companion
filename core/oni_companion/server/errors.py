"""One error type for views and routes. code is one of api.schema.json Error codes."""


class ApiError(Exception):
    STATUS = {"bad_request": 400, "bad_token": 403, "not_found": 404,
              "no_data": 503, "unavailable": 503, "not_in_v1": 501, "internal": 500,
              "unauthorized": 401, "rate_limited": 429, "local_only": 403, "bad_code": 403}

    def __init__(self, code, message, retry_after=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after       # seconds, sent as Retry-After with a 429

    @property
    def http_status(self):
        return self.STATUS.get(self.code, 500)

    def body(self):
        return {"error": {"code": self.code, "message": self.message}}


# Views raise ViewError(code, message) too.
ViewError = ApiError
