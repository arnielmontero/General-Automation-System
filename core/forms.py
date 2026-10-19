from django import forms

from .models import Role
from .modules import ALL_CODES, MODULES


class RoleForm(forms.ModelForm):
    modules = forms.MultipleChoiceField(
        choices=[(m.code, m.label) for m in MODULES],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ["name", "description", "is_default", "modules"]
        labels = {"is_default": "Default role for new users (given on their first login)"}
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Warehouse"}),
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "What this role is for"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Role.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A role with this name already exists.")
        return name

    def clean_modules(self):
        chosen = set(self.cleaned_data["modules"])
        return [code for code in ALL_CODES if code in chosen]  # keep declaration order
