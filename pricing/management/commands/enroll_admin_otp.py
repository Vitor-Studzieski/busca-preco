from base64 import b32decode
from binascii import Error
from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Vincula um autenticador TOTP ao administrador técnico."

    def add_arguments(self, parser):
        parser.add_argument("username")

    @transaction.atomic
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(
            username=options["username"], is_staff=True, is_active=True
        ).select_for_update().first()
        if not user:
            raise CommandError("Administrador técnico ativo não encontrado.")
        provided = "".join(getpass("Chave Base32 do autenticador (20 bytes): ").split()).rstrip("=")
        try:
            key = b32decode(provided.upper() + "=" * (-len(provided) % 8), casefold=True)
        except (Error, ValueError) as error:
            raise CommandError("Chave Base32 inválida.") from error
        if len(key) != 20:
            raise CommandError("Use uma chave aleatória de 20 bytes do seu gerenciador de segredos.")
        device = TOTPDevice.objects.create(user=user, name="Administração", key=key.hex(), confirmed=False)
        code = getpass("Código atual de seis dígitos: ").strip()
        if not code.isascii() or not code.isdigit() or len(code) != 6 or not device.verify_token(code):
            raise CommandError("O código do autenticador não conferiu.")
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        self.stdout.write("Autenticador confirmado. Use o próximo código ao acessar a administração.")
