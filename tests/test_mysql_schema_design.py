from __future__ import annotations

from django.apps import apps
from django.db import models


MYSQL_UTF8MB4_INDEX_BYTE_LIMIT = 1000


def test_declared_indexes_fit_current_mysql_key_length_limit():
    offenders: list[str] = []

    for model in apps.get_models():
        for field in model._meta.fields:
            if field.unique:
                _append_index_length_offender(
                    offenders,
                    model=model,
                    kind="unique field",
                    name=field.name,
                    fields=[field.name],
                )
            elif field.db_index:
                _append_index_length_offender(
                    offenders,
                    model=model,
                    kind="db_index field",
                    name=field.name,
                    fields=[field.name],
                )

        for constraint in model._meta.constraints:
            fields = list(getattr(constraint, "fields", []) or [])
            if fields:
                _append_index_length_offender(
                    offenders,
                    model=model,
                    kind=constraint.__class__.__name__,
                    name=getattr(constraint, "name", ""),
                    fields=fields,
                )

        for index in model._meta.indexes:
            fields = list(getattr(index, "fields", []) or [])
            if fields:
                _append_index_length_offender(
                    offenders,
                    model=model,
                    kind="Index",
                    name=getattr(index, "name", ""),
                    fields=fields,
                )

    assert offenders == []


def _append_index_length_offender(
    offenders: list[str],
    *,
    model: type[models.Model],
    kind: str,
    name: str,
    fields: list[str],
) -> None:
    estimated_bytes = 0
    details: list[str] = []

    for raw_field_name in fields:
        field_name = raw_field_name[1:] if raw_field_name.startswith("-") else raw_field_name
        field = model._meta.get_field(field_name)
        field_bytes = _field_index_bytes(field)
        details.append(f"{field_name}:{field.__class__.__name__}:{field_bytes}")
        if field_bytes is None:
            offenders.append(f"{model._meta.label}.{kind}.{name} indexes an unbounded field: {', '.join(details)}")
            return
        estimated_bytes += field_bytes

    if estimated_bytes > MYSQL_UTF8MB4_INDEX_BYTE_LIMIT:
        offenders.append(
            f"{model._meta.label}.{kind}.{name} estimates {estimated_bytes} bytes: {', '.join(details)}"
        )


def _field_index_bytes(field: models.Field) -> int | None:
    if isinstance(field, (models.CharField, models.SlugField, models.EmailField, models.URLField)):
        if field.max_length is None:
            return None
        return field.max_length * 4
    if isinstance(field, (models.TextField, models.JSONField, models.BinaryField)):
        return None
    if isinstance(field, (models.DateTimeField, models.DateField, models.TimeField)):
        return 8
    if isinstance(field, (models.DecimalField, models.FloatField)):
        return 16
    if isinstance(field, (models.BigAutoField, models.BigIntegerField, models.ForeignKey, models.OneToOneField)):
        return 8
    if isinstance(
        field,
        (
            models.AutoField,
            models.IntegerField,
            models.PositiveIntegerField,
            models.SmallIntegerField,
            models.PositiveSmallIntegerField,
        ),
    ):
        return 4
    if isinstance(field, models.BooleanField):
        return 1
    return 16
