# Lessons Learned

## Migraciones con UniqueConstraint

**Problema:** Migración que añade `UniqueConstraint` falla si existen datos duplicados en la DB.

**Solución:** Siempre añadir un paso `RunPython` antes del `AddConstraint` que:
1. Busca duplicados con `.values(...).annotate(count=Count('id'), min_id=Min('id')).filter(count__gt=1)`
2. Elimina los duplicados manteniendo el registro más antiguo (min id)
3. Imprime cuántos se eliminaron

**Regla:** Nunca crear una migración con `AddConstraint` sin limpieza previa de duplicados.
