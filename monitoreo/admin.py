from django.contrib import admin

from .models import EventoEntrega, EventoOcupacion, Mesa, Personal


@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ("numero", "camara_id", "capacidad", "activa")
    list_filter = ("activa", "camara_id")
    filter_horizontal = ("mesas_adyacentes",)


@admin.register(Personal)
class PersonalAdmin(admin.ModelAdmin):
    list_display = ("codigo_tracking", "alias", "primera_deteccion", "activo")
    list_filter = ("activo",)
    search_fields = ("codigo_tracking", "alias")


class EventoEntregaInline(admin.TabularInline):
    model = EventoEntrega
    extra = 0


@admin.register(EventoOcupacion)
class EventoOcupacionAdmin(admin.ModelAdmin):
    list_display = ("mesa", "inicio", "fin", "estado", "num_personas_detectadas", "tiene_clip")
    list_filter = ("estado", "mesa")
    date_hierarchy = "inicio"
    inlines = [EventoEntregaInline]
    readonly_fields = ("clip_s3_url",)

    @admin.display(boolean=True, description="Clip S3")
    def tiene_clip(self, obj):
        return bool(obj.clip_s3_key)


@admin.register(EventoEntrega)
class EventoEntregaAdmin(admin.ModelAdmin):
    list_display = ("evento_ocupacion", "personal", "tipo", "timestamp", "tiempo_espera_segundos")
    list_filter = ("tipo",)
