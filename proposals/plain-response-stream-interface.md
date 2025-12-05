# plain: Investigate stream-like interface on Response

- `ResponseBase` and `Response` implement file-like methods (`write`, `writelines`, `writable`, `seekable`, etc.)
- These methods aren't used anywhere in the codebase
- Investigate whether this interface is necessary or can be simplified

## Questions to answer

- Are these methods required by WSGI spec?
- Do any third-party libraries depend on this interface?
- Is there a use case for treating responses as writable streams?

## Implementation (if removable)

- Remove unused file-like methods from `ResponseBase` and `Response`
- Simplify the response classes

## Benefits

- Simpler response classes
- Less code to maintain
- Clearer API surface
