from django import forms
from .models import Certificado

from django import forms
from .models import Certificado

class CertificadoForm(forms.ModelForm):
    class Meta:
        model = Certificado
        fields = ['nombre', 'archivo', 'clave']

class PDFUploadForm(forms.Form):
    razon = forms.CharField(max_length=200)
    localizacion = forms.CharField(max_length=200)
    fecha = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))