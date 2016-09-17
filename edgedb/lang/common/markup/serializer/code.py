##
# Copyright (c) 2011 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##

from edgedb.lang.common.markup.elements import code as code_el

try:
    from pygments import token, lexers

except ImportError:
    # No pygments

    def serialize_code(code, lexer='does not matter'):
        return code_el.Code(tokens=[code_el.Token(val=code)])

else:
    import functools

    _TOKEN_MAP = {
        token.Token: code_el.Token,
        token.Whitespace: code_el.Whitespace,
        token.Comment: code_el.Comment,
        token.Keyword: code_el.Keyword,
        token.Keyword.Type: code_el.Type,
        token.Keyword.Constant: code_el.Constant,
        token.Operator: code_el.Operator,
        token.Operator.Word: code_el.Keyword,
        token.Name: code_el.Name,
        token.Name.Builtin: code_el.BuiltinName,
        token.Name.Function: code_el.FunctionName,
        token.Name.Class: code_el.ClassName,
        token.Name.Constant: code_el.Constant,
        token.Name.Decorator: code_el.Decorator,
        token.Name.Attribute: code_el.Attribute,
        token.Name.Tag: code_el.Tag,
        token.Name.Builtin.Pseudo: code_el.Constant,
        token.Punctuation: code_el.Punctuation,
        token.String: code_el.String,
        token.Number: code_el.Number,
        token.Error: code_el.Error
    }

    @functools.lru_cache(100)
    def get_code_class(token_type):
        cls = _TOKEN_MAP.get(token_type)
        while cls is None:
            token_type = token_type[:-1]
            cls = _TOKEN_MAP.get(token_type)

        if cls is None:
            cls = code_el.Token

        return cls

    class MarkupFormatter:
        def format(self, tokens):
            result = []

            for token_type, value in tokens:
                cls = get_code_class(token_type)
                result.append(cls(val=value))

            return code_el.Code(tokens=result)

    def serialize_code(code, lexer='python'):
        lexer = lexers.get_lexer_by_name(lexer, stripall=True)
        return MarkupFormatter().format(lexer.get_tokens(code))
