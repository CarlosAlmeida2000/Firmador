# Aplicación web para firmar PDF electrónicamente con archivo .p12 usando Django

# Estructura principal:
# - Django backend: subida de certificado, carga de PDF y firma con PyHanko
# - JavaScript frontend: posicionamiento de firma sobre PDF (usando PDF.js)
# - HTML/CSS: interfaces modernas con Tailwind CSS

# settings.py: asegúrate de tener configuradas rutas de medios y archivos estáticos

# models.py
from django.db import models

class Certificado(models.Model):
    nombre = models.CharField(max_length=100)
    archivo = models.FileField(upload_to='certificados/')
    clave = models.CharField(max_length=100)
    creado = models.DateTimeField(auto_now_add=True)

# forms.py
from django import forms
from .models import Certificado

class CertificadoForm(forms.ModelForm):
    class Meta:
        model = Certificado
        fields = ['nombre', 'archivo', 'clave']

class PDFUploadForm(forms.Form):
    pdf = forms.FileField()
    razon = forms.CharField(max_length=200)
    localizacion = forms.CharField(max_length=200)
    fecha = forms.DateTimeField(widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))