from plain.http import Response


class ResponseException(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(response)
