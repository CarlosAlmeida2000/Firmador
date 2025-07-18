import os, io, qrcode
from django.shortcuts import render, redirect
from .forms import CertificadoForm, PDFUploadForm
from .models import Certificado
from django.conf import settings
from django.http import FileResponse
from PIL import Image, ImageDraw, ImageFont
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat import backends
from endesive.pdf import cms
from datetime import timedelta
from cryptography.x509.oid import NameOID
from django.conf import settings


CERT_PATH = os.path.join(settings.MEDIA_ROOT, 'certificados')



def upload_certificado(request):
    if request.method == 'POST':
        form = CertificadoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('firmar_pdf')
    else:
        form = CertificadoForm()
    return render(request, 'upload_cert.html', {'form': form})


def dividir_nombre_multilinea(nombre_firmante, font, draw, ancho_maximo=200, max_lineas=3):
    palabras = nombre_firmante.upper().split()
    lineas = []
    linea_actual = ""

    for palabra in palabras:
        test_linea = (linea_actual + " " + palabra).strip()
        if draw.textlength(test_linea, font=font) <= ancho_maximo:
            linea_actual = test_linea
        else:
            lineas.append(linea_actual)
            linea_actual = palabra
            if len(lineas) == max_lineas - 1:
                break

    lineas.append(linea_actual)
    #lineas.append("DFDFDF")
    #lineas.pop(0)
    restantes = palabras[len(" ".join(lineas).split()):]
    if restantes:
        lineas[-1] += " " + " ".join(restantes)

    return lineas[:max_lineas]


def crear_estampa_firma(nombre_firmante, razon, localizacion, fecha):
    # Texto del QR
    qr_text = f"""FIRMADO POR: {nombre_firmante}\nRAZON: {razon}\nLOCALIZACION: {localizacion}\nFECHA: {fecha}\nVALIDAR CON: https://www.firmadigital.gob.ec\nFirmado digitalmente con FirmaEC 4.0.0 Windows 10 10.0"""

    # Crear QR
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=0
    )
    qr.add_data(qr_text)
    qr.make(fit=True)
    qr_img_rgb = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img_cropped = qr_img_rgb.crop(qr_img_rgb.getbbox())
    qr_final = qr_img_cropped.resize((100, 105), resample=Image.Resampling.NEAREST)

    # Crear estampa
    ancho, alto = 300, 105
    estampa = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    estampa.paste(qr_final.convert("RGBA"), (0, 0))

    draw = ImageDraw.Draw(estampa)
    try:
        font_bold = ImageFont.truetype("arialbd.ttf", 13)
        font_light = ImageFont.truetype("arial.ttf", 9)
    except:
        font_bold = font_light = ImageFont.load_default()

    margen_izquierdo = 102

    # Dividir nombre en 1–3 líneas
    lineas_nombre = dividir_nombre_multilinea(nombre_firmante, font_bold, draw)

    # Dibujar líneas
    # Determinar posición inicial en Y según cantidad de líneas
    coordenada_inicial = 18 if len(lineas_nombre) == 3 else 23 if len(lineas_nombre) == 2 else 30

    draw.text((margen_izquierdo, coordenada_inicial), "Firmado electrónicamente por:", font=font_light, fill='gray')

    y = coordenada_inicial + 12
    for linea in lineas_nombre:
        draw.text((margen_izquierdo, y), linea, font=font_bold, fill='black')
        y += 14  # Espacio entre líneas

    draw.text((margen_izquierdo, y + 10), "Validar únicamente con FirmaEC", font=font_light, fill='gray')

    # Guardar imagen
    carpeta_temp = os.path.join(settings.MEDIA_ROOT, 'temp')
    os.makedirs(carpeta_temp, exist_ok=True)
    ruta = os.path.join(carpeta_temp, 'firma_estampa.png')
    estampa.save(ruta, format='PNG')

    return ruta




def firmar_pdf(request):

    if request.method == 'POST':

        # Recupera el formulario enviado
        form = PDFUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:

                # Obtener datos del ultimo certificado de firma electronica desde la base de datos
                certificado = Certificado.objects.latest('creado')
                with open(certificado.archivo.path, 'rb') as f:
                    p12_data = f.read()

                # Cargar certificado de firma electrónica con la clave
                p12 = pkcs12.load_key_and_certificates(
                    p12_data, certificado.clave.encode("ascii"), backends.default_backend()
                )

                cert_x509 = p12[1]
                nombre_firmante = cert_x509.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value

                # Obtener datos del formulario
                pdf_file = request.FILES['pdf']
                coords = request.POST.get('coords')
                x_str, y_str, page_str = coords.split(',')
                x = float(x_str)
                y = float(y_str)
                page = int(page_str) 
                razon = form.cleaned_data['razon']
                localizacion = form.cleaned_data['localizacion']
                fecha_firma = form.cleaned_data['fecha']

                # Crear estampa QR de la firma electrónica
                ruta_estampa = crear_estampa_firma(nombre_firmante, razon, localizacion, fecha_firma.isoformat())

                # Despues de crear el QR se transforma la fecha por motivos de zona horario del firmado aumentando 5 horas
                fecha_firma = fecha_firma + timedelta(hours=5)
                date_str = fecha_firma.strftime('%Y%m%d%H%M%S+00\'00\'')
                
                dct = {
                    "aligned": 0,
                    "sigflags": 3,
                    "sigflagsft": 132,
                    "sigpage": (page - 1),
                    "sigbutton": True,
                    "sigfield": "Signature1",
                    "auto_sigfield": True,
                    "sigandcertify": True,
                    "signaturebox": (x, y, x + 108, y + 36),  
                    "signature_img": ruta_estampa,
                    "contact": nombre_firmante,
                    "location": localizacion,
                    "signingdate": date_str,
                    "reason": razon,
                    "password": certificado.clave.encode("ascii"),
                }

                # Firmar documento electrónicamente
                datau = pdf_file.read()
                datas = cms.sign(datau, dct, p12[0], p12[1], p12[2], "sha256")
                archivo_pdf_firmado = io.BytesIO()
                archivo_pdf_firmado.write(datau)
                archivo_pdf_firmado.write(datas)
                archivo_pdf_firmado.seek(0)

                return FileResponse(archivo_pdf_firmado, as_attachment=True, filename="firmado-signed.pdf")

            except Exception as e:
                print(str(e))
                return render(request, 'firmar_pdf.html', {'form': form})

    else:
        form = PDFUploadForm()
    return render(request, 'firmar_pdf.html', {'form': form})
