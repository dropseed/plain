from jinja2 import nodes
from jinja2.ext import Extension

class InclusionTagExtension(Extension):
    """Intended to be subclassed"""
    # tags = {'inclusion_tag'}
    tags: set[str]
    template_name: str

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        # tag_name = parser.stream.current.value
        # args = [parser.parse_expression()]

        # while parser.stream.skip_if('comma'):
        #     args.append(parser.parse_expression())

        call = self.call_method('_render', args=[nodes.ContextReference()], lineno=lineno)
        return nodes.CallBlock(call, [], [], []).set_lineno(lineno)

    def _render(self, context, *args, **kwargs):
        context = self.get_context(context, *args, **kwargs)
        template = self.environment.get_template(self.template_name)
        return template.render(context)

    def get_context(self, context, *args, **kwargs):
        raise NotImplementedError("You need to implement the `get_context` method in your subclass.")
