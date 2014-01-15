# encoding: utf-8
#
# Copyright (c) 2009 Thomas Kongevold Adamcik
#
# Snippet is released under the MIT License. So feel free to use it in other
# projects as long as the notice remains intact :)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# See http://www.djangosnippets.org/snippets/1312/

'''
HTML Validation Middleware
==========================

Simple development middleware to ensure that responses validate as HTML.

Dependencies:
-------------

 - tidy (http://utidylib.berlios.de/)

Installation:
-------------

Assuming this file has been place in your PYTHON_PATH (e.g.
djangovalidation/middleware.py), simply add the following
to your middleware settings:

  'djangovalidation.middleware.HTMLValidationMiddleware',

Remember that the order of your middleware settings does matter, this
middleware should be placed before eg. GzipMiddleware, djangologging and
any other middlewares that modify the response's content.

Operation:
----------

Validation only kicks in under to following conditions:
 - DEBUG == True
 - HTML_VALIDATION_ENABLE == True (default)
 - REMOTE_ADDR in INTERNAL_IPS
 - 'html' in Content-Type
 - 'disable-validation' not in GET
 - request.is_ajax() == False
 - type(response) == HttpResponse
 - request.path doesn't match HTML_VALIDATION_URL_IGNORE

To bypass the check any uri can be appended with ?disable-validation

Settings:
---------

 - HTML_VALIDATION_ENABLE     - Turns middleware on/off. Default: True

 - HTML_VALIDATION_ENCODING   - Default: 'utf-8'

 - HTML_VALIDATION_DOCTYPE    - Default: 'strict'

 - HTML_VALIDATION_IGNORE     - Default: ['trimming empty <option>',
                                          '<table> lacks "summary" attribute']

 - HTML_VALIDATION_URL_IGNORE - List of regular expressions to check
                                request.path against when deciding if we should
                                process the request. Default: [],

 - HTML_VALIDATION_XHTML      - Default: True

 - HTML_VALIDATION_OPTIONS    - Options that get passed to tidy, overrides
                                previous settings. Default: based on above
                                settings

For more information about settings use the source and consult tidy's
documentation.

History
-------

December 19, 2009:
 - Fix empty HTML_VALIDATION_URL_IGNORE. Thanks .iqqmuT

July 12, 2009:
 - Ignore ajax request
 - Add HTML_VALIDATION_URL_IGNORE settings

February 6, 2009:
 - Initial relase
'''

import re
import tidy

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse, HttpResponseServerError
from django.template import Context, Template

class HTMLValidationMiddleware(object):
    '''
        Checks that the response is valid HTML with proper Unicode. In the
        event of a failed check we show an simple page listing the HTML source
        and which errors need to be fixed.
    '''

    # Validation errors to ignore. Can be overridden with VALIDATION_IGNORE setting
    ignore = [
        'trimming empty <option>',
        '<table> lacks "summary" attribute',
    ]

    # Options for tidy. Can be overridden with HTML_VALIDATION_OPTIONS setting
    options = {
        'doctype': getattr(settings, 'HTML_VALIDATION_DOCTYPE', 'strict'),
        'output_xhtml': getattr(settings, 'HTML_VALIDATION_XHTML', True),
        'input_encoding': getattr(settings, 'HTML_VALIDATION_ENCODING', 'utf8'),
    }

    def __init__(self):
        if not settings.DEBUG or not getattr(settings, 'HTML_VALIDATION_ENABLE', True):
            raise MiddlewareNotUsed

        self.options = getattr(settings, 'HTML_VALIDATION_OPTIONS', self.options)
        self.ignore = set(getattr(settings, 'HTML_VALIDATION_IGNORE', self.ignore))
        self.ignore_regexp = self._build_ignore_regexp(getattr(settings, 'HTML_VALIDATION_URL_IGNORE', []))
        self.template = Template(self.HTML_VALIDATION_TEMPLATE.strip())

    def process_response(self, request, response):
        if not self._should_validate(request, response):
            return response

        errors = self._validate(response)

        if not errors:
            return response

        context = self._get_context(response, errors)

        return HttpResponseServerError(self.template.render(context))

    def _build_ignore_regexp(self, urls):
        if not urls:
            return None

        urls = [r'(%s)' % url for url in urls]
        return re.compile(r'(%s)' % r'|'.join(urls))

    def _should_validate(self, request, response):
        return ('html' in response['Content-Type'] and
                'disable-validation' not in request.GET and
                not request.is_ajax() and
                (not self.ignore_regexp or 
                 not self.ignore_regexp.search(request.path)) and
                request.META['REMOTE_ADDR'] in settings.INTERNAL_IPS and
                type(response) == HttpResponse)

    def _validate(self, response):
        errors = tidy.parseString(response.content, **self.options).errors
        return self._filter_errors(errors)

    def _filter_errors(self, errors):
        return filter(lambda e: e.message not in self.ignore, errors)

    def _get_context(self, response, errors):
        lines = []
        error_dict = dict(map(lambda e: (e.line, e.message), errors))

        for i, line in enumerate(response.content.split('\n')):
            lines.append((line, error_dict.get(i + 1, False)))

        return Context({'errors': errors,
                        'lines': lines,})

    HTML_VALIDATION_TEMPLATE = """
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html lang="en">
<head>
  <meta http-equiv="content-type" content="text/html; charset=utf-8">
  <title>HTML validation error at {% templatetag openvariable %} request.path_info|escape {% templatetag closevariable %}</title>
  <meta name="robots" content="NONE,NOARCHIVE">
  <style type="text/css">
    html * { padding: 0; margin: 0; }
    body * { padding: 10px 20px; }
    body * * { padding: 0; }
    body { font: small sans-serif; background: #eee; }
    body>div { border-bottom: 1px solid #ddd; }
    h1 { font-weight: normal; margin-bottom: 0.4em; }
    table { border: none; border-collapse: collapse; width: 100%; }
    td, th { vertical-align: top; padding: 2px 3px; }
    th { width: 6em; text-align: right; color: #666; padding-right: 0.5em; }
    #info { background: #f6f6f6; }
    #info th { width: 3em; }
    #summary { background: #ffc; }
    #explanation { background: #eee; border-bottom: 0px none; }
    .meta { margin: 1em 0; }
    .error { background: #FEE }
  </style>
</head>
<body>
  <div id="summary">
    <h1>HTML validation error</h1>
    <p>
        Your HTML did not validate. If this page contains user content that
        might be the problem. Please fix the following:
    </p>
    <table class="meta">
      {% templatetag openblock %} for error in errors {% templatetag closeblock %}
        <tr>
          <th>Line: <a href="#line{% templatetag openvariable %} error.line {% templatetag closevariable %}">{% templatetag openvariable %} error.line {% templatetag closevariable %}</a></th>
          <td>{% templatetag openvariable %} error.message|escape {% templatetag closevariable %}</td>
        </tr>
      {% templatetag openblock %} endfor {% templatetag closeblock %}
    </table>
    <p>
      If you want to bypass this warning, click <a href="?disable-validation">
      here</a>. Please note that this warning will persist until you fix the
      problems mentioned above.
    </p>
  </div>
  <div id="info">
    <table>
      {% templatetag openblock %} for line,error in lines {% templatetag closeblock %}
        <tr{% templatetag openblock %} if error {% templatetag closeblock %} class="error"{% templatetag openblock %} endif {% templatetag closeblock %}>
          <th id="line{% templatetag openvariable %} forloop.counter {% templatetag closevariable %}">
            {% templatetag openvariable %} forloop.counter|stringformat:"03d" {% templatetag closevariable %}
          </th>
          <td{% templatetag openblock %} if error {% templatetag closeblock %} title="{% templatetag openvariable %} error {% templatetag closevariable %}"{% templatetag openblock %} endif {% templatetag closeblock %}>
            <pre>{% templatetag openvariable %} line {% templatetag closevariable %}</pre>
          </td>
        </tr>
      {% templatetag openblock %} endfor {% templatetag closeblock %}
    </table>
  </div>

  <div id="explanation">
    <p>
      You're seeing this error because you have not set
      <code>HTML_VALIDATION_ENABLE = False</code> in your Django settings file.
      Change that to <code>False</code>, and Django will stop validating your
      HTML.
    </p>
  </div>
</body>
</html>"""
