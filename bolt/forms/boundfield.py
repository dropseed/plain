from functools import cached_property

__all__ = ("BoundField",)


class BoundField:
    "A Field plus data"

    def __init__(self, form, field, name):
        self._form = form
        self.field = field
        self.name = name
        self.html_name = form.add_prefix(name)
        self.html_id = form.add_prefix(self._auto_id)

    def __repr__(self):
        return f'<{self.__class__.__name__} "{self.html_name}">'

    @property
    def errors(self):
        """
        Return an error list (empty if there are no errors) for this field.
        """
        return self._form.errors.get(self.name, [])

    def value(self):
        """
        Return the value for this BoundField, using the initial value if
        the form is not bound or the data otherwise.
        """
        data = self.initial
        if self._form.is_bound:
            data = self.field.bound_data(
                self._form._field_data_value(self.field, self.html_name), data
            )
        return self.field.prepare_value(data)

    @cached_property
    def initial(self):
        return self._form.get_initial_for_field(self.field, self.name)

    def _has_changed(self):
        return self.field.has_changed(
            self.initial, self._form._field_data_value(self.field, self.html_name)
        )

    @property
    def _auto_id(self):
        """
        Calculate and return the ID attribute for this BoundField, if the
        associated Form has specified auto_id. Return an empty string otherwise.
        """
        auto_id = self._form._auto_id  # Boolean or string
        if auto_id and "%s" in str(auto_id):
            return auto_id % self.html_name
        elif auto_id:
            return self.html_name
        return ""
