class ResponseException(Exception):
    def __init__(self, response):
        self.response = response
        super().__init__(response)
