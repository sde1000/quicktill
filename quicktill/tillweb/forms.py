from django.forms import Form
from django.forms.fields import Field
from django.forms.widgets import Widget
from django.forms.widgets import Select, SelectMultiple, MultipleHiddenInput
from django.core.exceptions import ValidationError
from django.utils.translation import gettext, gettext_lazy as _
from sqlalchemy import inspect
from .db import td
import copy
import json

class _model_choice_iterator:
    def __init__(self, field):
        self.field = field

    def __iter__(self):
        # XXX I can't see how to access the bound field's initial data
        # here.  self.field.initial will only ever have data if it was
        # passed in at field creation time, not when the form has an
        # initial dict passed to it.

        if self.field.empty_label is not None \
           and not self.field._multiple_choices \
           and ((self.field.required and not self.field.initial)
                or not self.field.required):
            yield ("", self.field.empty_label)

        mq = td.s.query(self.field.model)
        mq = self.field.query_filter(mq)
        yield from ((self.field.model_to_value(x), self.field.label_function(x))
                    for x in mq.all())

# Fields

class SQLAModelChoiceField(Field):
    """A Field whose choices are sqlalchemy ORM model instances

    Does not inherit from ChoiceField because that would not be helpful!

    model must be a sqlalchemy ORM model

    There's no general way to get an option value from a model
    instance and then a model instance from an option value.  (repr()
    on the identity map key is one possible idea, but retrieving it
    from the string version is difficult.)  Instead, create a subclass
    and override the model_to_value and values_to_filter methods if
    your model doesn't have an integer 'id' field as primary key.
    """
    widget = Select
    _multiple_choices = False
    default_error_messages = {
        'invalid_choice': _('Select a valid choice. That choice is not one of'
                            ' the available choices.'),
        'invalid_list': _('Enter a list of values.'),
    }

    def __init__(self, model, *, empty_label=None,
                 required=True, widget=None, label=None, initial=None,
                 help_text='', label_function=str, query_filter=lambda x: x,
                 **kwargs):
        self.empty_label = empty_label if empty_label \
                           else f"Choose a {model.__name__}"
        super().__init__(
            required=required, widget=widget, label=label,
            initial=initial, help_text=help_text, **kwargs)
        self._choices = None
        self.model = model
        self.label_function = label_function
        self.query_filter = query_filter

    def model_to_value(self, model):
        """Return a string that is unique to the model"""
        return str(model.id)

    # Called to deal with initial data - convert from model instance to string
    def prepare_value(self, value):
        if isinstance(value, self.model):
            return self.model_to_value(value)
        return value

    def values_to_filter(self, query, values):
        """Update the query to filter for a list of values

        "values" is supposed to be a list of unique strings.
        """
        try:
            return query.filter(self.model.id.in_(int(x) for x in values))
        except:
            raise ValidationError(self.error_messages['invalid_choice'],
                                  code='invalid_choice')

    @property
    def choices(self):
        return _model_choice_iterator(self)

    def __deepcopy__(self, memo):
        # The superclass will copy the widget, error messages and validators
        result = super().__deepcopy__(memo)

        # XXX We take this opportunity to set the choices in the
        # widget: it doesn't feel right, but this is the only place I
        # can find to do it!
        if hasattr(result.widget, 'choices'):
            result.widget.choices = self.choices
        if hasattr(result.widget, 'empty_label'):
            result.widget.empty_label = self.empty_label
        if hasattr(result.widget, 'value_to_label'):
            result.widget.label_function = lambda x:self.label_function(self.to_python(x))

        # Opinion: django's use of special-case __deepcopy__ all over
        # the forms, fields and widgets implementations is a complete
        # hack and looks very fragile.  There's a lot of conflation of
        # "template" objects whose instances are created at form class
        # definition time with "working" objects that are created for
        # each web request.  Really these ought to be different types,
        # i.e. an extra layer, with the templates being factories for
        # the working objects.

        # But we're not going to rewrite django's forms system here,
        # so we just have to live with it...
        return result

    def to_python(self, value):
        """Return a model"""
        if value in self.empty_values:
            return None
        try:
            query = self.query_filter(td.s.query(self.model))
            r = self.values_to_filter(query, [value]).all()
            if len(r) != 1:
                return None
            return r[0]
        except:
            raise ValidationError(self.error_messages['invalid_choice'],
                                  code='invalid_choice')

    def validate(self, value):
        """Validate that the input is a valid choice"""
        if self.required and not value:
            raise ValidationError(self.error_messages['required'],
                                  code='required')

class SQLAModelMultipleChoiceField(SQLAModelChoiceField):
    hidden_widget = MultipleHiddenInput
    widget = SelectMultiple
    _multiple_choices = True

    def prepare_value(self, value):
        if (hasattr(value, '__iter__') and
            not isinstance(value, str) and
            not hasattr(value, '_meta')):
            prepare_value = super().prepare_value
            return [prepare_value(v) for v in value]
        return super().prepare_value(value)

    def to_python(self, value):
        if not value:
            return []
        elif not isinstance(value, (list, tuple)):
            raise ValidationError(self.error_messages['invalid_list'],
                                  code='invalid_list')
        query = self.query_filter(td.s.query(self.model))
        r = self.values_to_filter(query, value).all()
        if len(r) != len(value):
            raise ValidationError(self.error_messages['invalid_choice'],
                                  code='invalid_choice')
        return r

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        if initial is None:
            initial = []
        if data is None:
            data = []
        if len(initial) != len(data):
            return True
        initial_set = set(initial)
        data_set = set(data)
        return data_set != initial_set

class _StringIDMixin:
    """SQL Alchemy model field with string primary key
    """
    def values_to_filter(self, query, values):
        try:
            return query.filter(self.model.id.in_(values))
        except:
            raise ValidationError(self.error_messages['invalid_choice'],
                                  code='invalid_choice')

class StringIDChoiceField(_StringIDMixin, SQLAModelChoiceField):
    """SQL Alchemy model choice field with string primary key
    """
    pass

class StringIDMultipleChoiceField(_StringIDMixin, SQLAModelMultipleChoiceField):
    """SQL Alchemy model multiple choice field with string primary key
    """
    pass

# Widgets

# Subclass the existing Select and SelectMultiple widgets to enable
# select2 where options are rendered in the page

class _select2_mixin:
    # XXX add a Media class here?

    empty_label = ''

    def build_attrs(self, base_attrs, extra_attrs=None):
        default_attrs = {'data-minimum-input-length': 0}
        default_attrs['data-placeholder'] = self.empty_label
        if self.is_required:
            default_attrs['data-allow-clear'] = 'false'
        else:
            default_attrs['data-allow-clear'] = 'true'

        default_attrs.update(base_attrs)
        attrs = super().build_attrs(default_attrs, extra_attrs=extra_attrs)
        return attrs

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        output = super().render(name, value, attrs=final_attrs, renderer=renderer)
        output += f'''
<script type="text/javascript">
  $(document).ready(function(){{
    $("#{final_attrs.get('id')}").select2();
}});
</script>'''
        return output

class Select2(_select2_mixin, Select):
    pass

class Select2Multiple(_select2_mixin, SelectMultiple):
    pass

# Implement a new widget to enable select2 where options are fetched using ajax

class Select2Ajax(Widget):
    template_name = 'tillweb/select2_widget.html'
    allow_multiple_selected = False

    def __init__(self, attrs=None, ajax={}, empty_label='', min_input_length=0):
        """ajax will be passed as the ajax option to select2()"""
        super().__init__(attrs)
        self.ajax = ajax
        self.min_input_length = min_input_length
        self.empty_label = empty_label
        self.value_to_label = str # will be set when copied by field

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['options'] = [
            (x, self.label_function(x))
            for x in context['widget']['value'] if x]
        select2_args = {"ajax": self.ajax, "placeholder": self.empty_label,
                        "minimumInputLength": self.min_input_length,
                        "allowClear": not self.is_required}
        context['widget']['select2_args'] = json.dumps(select2_args)
        print(f"context: {context}")
        return context

    def value_from_datadict(self, data, files, name):
        getter = data.get
        if self.allow_multiple_selected:
            getter = data.getlist
        return getter(name)

    def format_value(self, value):
        """Return selected values as a list."""
        if value is None and self.allow_multiple_selected:
            return []
        if not isinstance(value, (tuple, list)):
            value = [value]
        return [str(v) if v is not None else '' for v in value]

class Select2MultipleAjax(Select2Ajax):
    allow_multiple_selected = True
