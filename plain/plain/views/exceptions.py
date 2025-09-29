from plain.http import ResponseBase


class ResponseException(Exception):
    def __init__(self, response: ResponseBase) -> None:
        self.response = response
        super().__init__(response)
