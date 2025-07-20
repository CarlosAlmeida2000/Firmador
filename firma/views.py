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

### otra
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


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


def generar_pdf_con_estampa(pdf_original, nombre_firmante, x, y, page, lineas_nombre):
    # 1. Cargar el PDF original
    input_pdf = PdfReader(pdf_original)

    # 2. Crear PDF de estampa con ReportLab en memoria
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=letter)

    # Registrar fuente TTF
    font_path = os.path.join(settings.BASE_DIR, 'static/fonts/DejaVuSans.ttf')  # Asegúrate de tener esta ruta
    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))

    can.setFont('DejaVuSans', 4)
    can.setFillColorRGB(0, 0, 0)

    # Posición relativa (x, y) ajustada
    y_estampa = 18 if len(lineas_nombre) == 3 else 23 if len(lineas_nombre) == 2 else 30
    margen_izquierdo = 37

    can.drawString(x + margen_izquierdo, y + y_estampa, "Firmado electrónicamente por:")

    for linea in lineas_nombre:
        y_estampa -= 5  # Espacio entre líneas
        can.drawString(x + margen_izquierdo, y + y_estampa, linea)

    y_estampa -= 6
    can.drawString(x + margen_izquierdo, y + y_estampa, "Validar únicamente con FirmaEC")

    can.save()
    packet.seek(0)

    # 3. Combinar la estampa sobre el PDF original
    overlay_pdf = PdfReader(packet)
    output = PdfWriter()

    for i in range(len(input_pdf.pages)):
        page_pdf = input_pdf.pages[i]
        if i == page - 1:
            page_pdf.merge_page(overlay_pdf.pages[0])
        output.add_page(page_pdf)

    # 4. Guardar PDF temporal para firmar
    temp_pdf_path = os.path.join(settings.MEDIA_ROOT, 'temp', 'con_estampa.pdf')
    os.makedirs(os.path.dirname(temp_pdf_path), exist_ok=True)
    with open(temp_pdf_path, 'wb') as f:
        output.write(f)

    return temp_pdf_path


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

    # Guardar imagen j
    carpeta_temp = os.path.join(settings.MEDIA_ROOT, 'temp')
    os.makedirs(carpeta_temp, exist_ok=True)
    ruta = os.path.join(carpeta_temp, 'firma_estampa.png')
    estampa.save(ruta, format='PNG')

    return ruta


def crear_estampa_firma2(nombre_firmante, razon, localizacion, fecha):
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

    #draw.text((margen_izquierdo, coordenada_inicial), "Firmado electrónicamente por:", font=font_light, fill='gray')

    y = coordenada_inicial + 12
    for linea in lineas_nombre:
        #draw.text((margen_izquierdo, y), linea, font=font_bold, fill='black')
        y += 14  # Espacio entre líneas

    #draw.text((margen_izquierdo, y + 10), "Validar únicamente con FirmaEC", font=font_light, fill='gray')

    # Guardar imagen
    carpeta_temp = os.path.join(settings.MEDIA_ROOT, 'temp')
    os.makedirs(carpeta_temp, exist_ok=True)
    ruta = os.path.join(carpeta_temp, 'firma_estampa.png')
    estampa.save(ruta, format='PNG')

    return ruta, lineas_nombre


def firmar_pdf2(request):

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

                # Paso 1: Crear estampa de la firma electrónica
                ruta_estampa, lineas_nombre = crear_estampa_firma(nombre_firmante, razon, localizacion, fecha_firma.isoformat())


                ruta_pdf_con_estampa = generar_pdf_con_estampa(
                    pdf_original=pdf_file,
                    nombre_firmante=nombre_firmante,
                    x=x,
                    y=y,
                    page=page, 
                    lineas_nombre=lineas_nombre
                )

                # Paso 2: Preparar fecha para FirmaEC (zona horaria UTC+0)
                fecha_firma_utc = fecha_firma + timedelta(hours=5)
                date_str = fecha_firma_utc.strftime('%Y%m%d%H%M%S+00\'00\'')

                # Paso 3: Leer el PDF limpio ya con la estampa
                with open(ruta_pdf_con_estampa, 'rb') as f:
                    datau = f.read()

                # Paso 4: Diccionario de firma para endesive
                dct = {
                    "aligned": 0,
                    "sigflags": 3,
                    "sigflagsft": 132,
                    "sigpage": (page - 1),
                    "sigbutton": True,
                    "sigfield": "Signature1",
                    "auto_sigfield": True,
                    "sigandcertify": True,
                    "signaturebox": (x, y, x + 108, y + 36),  # Tamaño del cuadro de firma
                    "signature_img": ruta_estampa,
                    "contact": nombre_firmante,
                    "location": localizacion,
                    "signingdate": date_str,
                    "reason": razon,
                    "password": certificado.clave.encode("ascii"),
                }

                # Paso 5: Firmar con endesive
                datas = cms.sign(datau, dct, p12[0], p12[1], p12[2], "sha256")

                # Paso 6: Devolver solo la firma (no sobreescribas el PDF)
                output_pdf = io.BytesIO()
                output_pdf.write(datau)
                output_pdf.write(datas)
                output_pdf.seek(0)

                return FileResponse(output_pdf, as_attachment=True, filename="firmado-signed.pdf")

            except Exception as e:
                print(str(e))
                return render(request, 'firmar_pdf.html', {'form': form})

    else:
        form = PDFUploadForm()
    return render(request, 'firmar_pdf.html', {'form': form})








from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.fields import append_signature_field, SigFieldSpec
from pyhanko.sign.signers import PdfSignatureMetadata
from pyhanko import stamp
from pyhanko.pdf_utils import text
from pyhanko.sign import fields, signers



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

                #pdf_path = r'D:\env-firma-ec\Firmador\media\temp\Memorando Nro 158-signed.pdf'
                output_path = r'D:\env-firma-ec\Firmador\media\temp\con_estampa-signed.pdf'
                
                # Crear un firmante basado en el certificado
                signer = signers.SimpleSigner.load_pkcs12(pfx_file=certificado.archivo.path, passphrase=certificado.clave.encode('utf-8'))
                
                print("FIRMADA CARGADA")

                # Abrir el PDF para agregar la firma
                writer = IncrementalPdfFileWriter(pdf_file)

                fields.append_signature_field(
                    writer, sig_field_spec=fields.SigFieldSpec(
                        (nombre_firmante + str(fecha_firma)), 
                        box=(x, y, x + 120, y + 45), 
                        on_page=(page - 1)
                    )
                )

                meta = signers.PdfSignatureMetadata(field_name=(nombre_firmante + str(fecha_firma)))

                print("PDF CARGADO")
               
                pdf_signer = signers.PdfSigner(
                    meta, signer=signer, stamp_style=stamp.QRStampStyle(
                        #stamp_text='Signed by: %(signer)s\nTime: %(ts)s\nURL: %(url)s',
                        stamp_text='Firmado electrónicamente por: s\n %(signer)s\n Validar únicamente con FirmaEC',
                    ),
                )


                # Firmar el documento
                qr_text = f"""FIRMADO POR: {nombre_firmante}\nRAZON: {razon}\nLOCALIZACION: {localizacion}\nFECHA: {fecha_firma.isoformat()}\nVALIDAR CON: https://www.firmadigital.gob.ec\nFirmado digitalmente con FirmaEC 4.0.0 Windows 10 10.0"""

                with open(output_path, "wb") as output_file:
                    pdf_signer.sign_pdf(
                        writer,
                        output=output_file,
                        appearance_text_params={'url': qr_text}
                    )
                

                # Puedes mostrar el PDF firmado o devolverlo como descarga
                print("FIRMADOOOOOOOO")
                return render(request, 'firmar_pdf.html', {
                    'form': form,
                    'mensaje': 'Documento firmado correctamente.'
                })

            except Exception as e:
                print("Error en firma:", str(e))
                return render(request, 'firmar_pdf.html', {
                    'form': form,
                    'error': 'Ocurrió un error al firmar el documento.'
                })

    else:
        form = PDFUploadForm()
    return render(request, 'firmar_pdf.html', {'form': form})