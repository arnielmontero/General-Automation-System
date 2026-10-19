from django import forms
from django.conf import settings

from .services import normalize_so, validate_so


class NewRecordForm(forms.Form):
    so_number = forms.CharField(
        label="Sales Order (SO)",
        max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "e.g. S04743", "class": "form-control", "autofocus": True}),
    )
    pdf = forms.FileField(
        label="Packing list PDF",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf", "class": "form-control"}),
    )

    def clean_so_number(self):
        so = normalize_so(self.cleaned_data["so_number"])
        validate_so(so)
        return so

    def clean_pdf(self):
        pdf = self.cleaned_data["pdf"]
        if not pdf.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Please upload a PDF file.")
        if pdf.size > settings.MAX_PDF_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"The PDF is larger than {settings.MAX_PDF_UPLOAD_MB} MB.")
        head = pdf.read(5)
        pdf.seek(0)
        if head != b"%PDF-":
            raise forms.ValidationError("This file is not a valid PDF.")
        return pdf
