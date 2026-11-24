from django.db import migrations


def prepare(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    schema_editor.execute("""
        ALTER TABLE pricing_ownprice ADD CONSTRAINT own_price_no_overlap
        EXCLUDE USING gist (product_id WITH =, kind WITH =,
                            tstzrange(starts_at, ends_at, '[)') WITH &&)
        WHERE (cancelled_at IS NULL)
    """)
    schema_editor.execute("""
        CREATE INDEX pricing_product_search_trgm ON pricing_product
        USING gin (search_name gin_trgm_ops) WHERE active
    """)
    schema_editor.execute("""
        CREATE FUNCTION pricing_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'O histórico de auditoria é imutável'; END; $$
    """)
    schema_editor.execute("""
        CREATE TRIGGER pricing_audit_immutable BEFORE UPDATE OR DELETE ON pricing_auditlog
        FOR EACH ROW EXECUTE FUNCTION pricing_audit_append_only()
    """)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP TRIGGER pricing_audit_immutable ON pricing_auditlog")
    schema_editor.execute("DROP FUNCTION pricing_audit_append_only()")
    schema_editor.execute("DROP INDEX pricing_product_search_trgm")
    schema_editor.execute("ALTER TABLE pricing_ownprice DROP CONSTRAINT own_price_no_overlap")
    # Extensões podem ter outros consumidores no mesmo banco.


class Migration(migrations.Migration):
    dependencies = [("pricing", "0006_fluxo_comprador")]
    operations = [migrations.RunPython(prepare, reverse)]
