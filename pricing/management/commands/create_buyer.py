import os
from getpass import getpass

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from pricing.workflow_models import AuditLog


class Command(BaseCommand):
    help = "Cria uma das duas contas de comprador. Informe a senha pelo prompt ou ambiente."

    def add_arguments(self, parser):
        parser.add_argument("username")

    @transaction.atomic
    def handle(self, *args, **options):
        users = get_user_model()
        group, _ = Group.objects.get_or_create(name="Comprador")
        group = Group.objects.select_for_update().get(pk=group.pk)
        enrolled = users.objects.filter(is_staff=False, is_superuser=False).filter(
            Q(groups=group) | Q(user_permissions__content_type__app_label="pricing",
                                user_permissions__codename="view_product")
        ).distinct()
        if enrolled.count() >= 2:
            raise CommandError("As duas contas de comprador já foram provisionadas.")
        username = options["username"].strip()
        if not username or users.objects.filter(username__iexact=username).exists():
            raise CommandError("Informe um nome de usuário novo.")
        account = users(username=username)
        password = os.environ.get("PRICING_BUYER_PASSWORD") or getpass("Senha inicial: ")
        try:
            account.full_clean(exclude=["password"])
            password_validation.validate_password(password, account)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        account.set_password(password)
        account.save()
        group.permissions.set(Permission.objects.filter(content_type__app_label="pricing",
                                                        codename__in=["view_product", "add_pricedraft"]))
        account.groups.add(group)
        AuditLog.objects.create(actor=account, action="account.create_buyer")
        self.stdout.write(self.style.SUCCESS("Conta de comprador criada."))
