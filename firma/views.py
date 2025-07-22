import os, qrcode
from django.shortcuts import render, redirect
from .forms import CertificadoForm, PDFUploadForm
from .models import Certificado
from django.conf import settings
from django.http import FileResponse
from PIL import Image, ImageDraw, ImageFont
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat import backends
from cryptography.x509.oid import NameOID
from django.conf import settings
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko import stamp
from pyhanko.sign import fields, signers
from pyhanko.pdf_utils import text, images


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

    # Guardar imagen j
    carpeta_temp = os.path.join(settings.MEDIA_ROOT, 'temp')
    os.makedirs(carpeta_temp, exist_ok=True)
    ruta = os.path.join(carpeta_temp, 'estampa.png')
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

                #pdf_path = r'D:\env-firma-ec\Firmador\media\temp\Memorando Nro 158-signed.pdf'
                output_path = os.path.join(settings.MEDIA_ROOT, 'temp\con_estampa-signed.pdf')
                
                # Crear un firmante basado en el certificado
                signer = signers.SimpleSigner.load_pkcs12(pfx_file=certificado.archivo.path, passphrase=certificado.clave.encode('utf-8'))
                
                print("FIRMADA CARGADA")

                # Abrir el PDF para agregar la firma
                writer = IncrementalPdfFileWriter(pdf_file)

                fields.append_signature_field(
                    writer, sig_field_spec=fields.SigFieldSpec(
                        (nombre_firmante + str(fecha_firma)), 
                        box=(x, y, x + 120, y + 72), 
                        on_page=(page - 1)
                    )
                )

                meta = signers.PdfSignatureMetadata(
                    field_name=(nombre_firmante + str(fecha_firma))
                    )


                print("PDF CARGADO")
                
                pdf_signer = signers.PdfSigner(
                    meta, signer=signer, stamp_style=stamp.QRStampStyle(
                        stamp_text='Firmado electrónicamente por:\n%(signer)s\nValidar únicamente con FirmaEC',
                        border_width=0  # Esto sí es seguro en esta versión
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