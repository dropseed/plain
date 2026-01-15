class Img:
    def __init__(
        self,
        src: str,
        *,
        alt: str = "",
        width: int | None = None,
        height: int | None = None,
    ):
        self.src = src
        self.alt = alt
        self.width = width
        self.height = height


class Avatar:
    def __init__(self, src: str, *, alt: str = ""):
        self.src = src
        self.alt = alt
