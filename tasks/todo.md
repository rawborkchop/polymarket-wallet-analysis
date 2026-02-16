# Refactorización P&L y Métricas Polymarket

## Estado: COMPLETADO ✓

---

## Problemas Identificados

### CRÍTICOS
- [x] **P1: Doble fuente de P&L** - `trade_service.py` y `pnl_calculator.py` usan fórmulas diferentes
- [x] **P2: REDEEMs guardados doblemente** - como Trade (SELL) y como Activity (REDEEM)
- [x] **P3: Sobrescritura de P&L** - cada refresh pierde el histórico

### ALTOS
- [x] **P4: Pérdida de precisión** - uso de `float` en vez de `Decimal` desde el inicio
- [x] **P5: Inconsistencia en serialización** - diferentes endpoints retornan P&L diferente

### MEDIOS
- [x] **P6: Violaciones SOLID** - pnl_calculator tiene múltiples responsabilidades
- [x] **P7: Constraint unicidad débil** - falta `condition_id` en constraint
- [x] **P8: Errores silenciosos** - trades inválidos descartados sin logging

---

## Fases de Implementación

### Fase 1: Unificar Fuente de P&L ✓
**Objetivo:** Una sola fórmula de P&L en todo el sistema

- [x] 1.1 Definir `pnl_calculator.py` como ÚNICA fuente de verdad
- [x] 1.2 Modificar fórmula: `P&L = (sells + redeems + merges + rewards) - (buys + splits)`
- [x] 1.3 Actualizar `views.py` para usar solo `pnl_calculator`
- [x] 1.4 El campo `wallet.subgraph_realized_pnl` será solo cache (calculado por pnl_calculator)

**Archivos modificados:**
- `wallet_analysis/pnl_calculator.py`
- `wallet_analysis/views.py`
- `wallet_analysis/tasks.py`

### Fase 2: Separar Redeems de Trades ✓
**Objetivo:** REDEEMs solo en tabla Activity, no en Trade

- [x] 2.1 Eliminar conversión REDEEM→Trade en `trade_service.py:52-56`
- [x] 2.2 Actualizar `pnl_calculator.py` para incluir Activities en P&L
- [x] 2.3 Renombrar `total_pnl` a `preview_pnl` en cash_flow (no es fuente de verdad)

**Archivos modificados:**
- `src/services/trade_service.py`
- `wallet_analysis/services.py`

### Fase 3: Usar Decimal Desde el Inicio ✓
**Objetivo:** Eliminar pérdida de precisión

- [x] 3.1 Cambiar `float()` a `Decimal(str())` en `src/api/models.py`
- [x] 3.2 Agregar función `to_decimal()` helper
- [x] 3.3 Cambiar cálculos en `trade_service.py` a Decimal
- [x] 3.4 Verificar que `pnl_calculator.py` usa Decimal consistentemente

**Archivos modificados:**
- `src/api/models.py`
- `src/services/trade_service.py`

### Fase 4: Aplicar SOLID ✓
**Objetivo:** Mejorar mantenibilidad de pnl_calculator

- [x] 4.1 Crear estructura `wallet_analysis/calculators/`
- [x] 4.2 Crear `interfaces.py` con IPnLCalculator, ICashFlowProvider, IAggregator
- [x] 4.3 Crear `aggregators.py` con MarketAggregator, DailyAggregator
- [x] 4.4 Crear `pnl_calculator.py` con PnLCalculator class y DjangoCashFlowProvider
- [x] 4.5 Mantener compatibilidad hacia atrás con funciones module-level

**Archivos creados:**
- `wallet_analysis/calculators/__init__.py`
- `wallet_analysis/calculators/interfaces.py`
- `wallet_analysis/calculators/aggregators.py`
- `wallet_analysis/calculators/pnl_calculator.py`

### Fase 5: Arreglar Constraint Unicidad ✓
**Objetivo:** Evitar colisiones en trades

- [x] 5.1 Actualizar constraint para incluir `wallet` y `market`
- [x] 5.2 Crear migración `0004_update_trade_unique_constraint.py`

**Archivos modificados:**
- `wallet_analysis/models.py`
- `wallet_analysis/migrations/0004_update_trade_unique_constraint.py` (nuevo)

### Fase 6: Agregar Logging ✓
**Objetivo:** Visibilidad de errores

- [x] 6.1 Logging de trades descartados en `services.py`
- [x] 6.2 Logging de errores de constraint (bulk insert failures)
- [x] 6.3 Métricas de datos procesados vs guardados

**Archivos modificados:**
- `wallet_analysis/services.py`

### Fase 7: Fix Inconsistencias P&L ✓
**Objetivo:** Resolver bugs de sincronización entre vista lista y detalle

- [x] 7.1 Actualizar caché en /stats/ cuando se calcula P&L completo
- [x] 7.2 Usar calculate_wallet_pnl_filtered cuando hay filtro de fecha
- [x] 7.3 Filtrar trade stats por fecha (Total Trades, Buys, Sells)
- [x] 7.4 Detectar duplicados reales en bulk_create (visibilidad)

**Archivos modificados:**
- `wallet_analysis/views.py` (líneas 78-143)
- `wallet_analysis/services.py` (líneas 129-175)

---

## Verificación

### Tests manuales:
- [ ] Crear wallet con trades y redeems conocidos
- [ ] Verificar P&L en `/api/wallets/` == P&L en `/api/wallets/{id}/stats/`
- [ ] Verificar precisión decimal con valores pequeños (0.001 USDC)
- [ ] Ejecutar migración y verificar constraint funciona

### Tests Fase 7 (nuevos):
- [ ] Abrir wallet "1pixel" en dashboard → P&L = $94.58K
- [ ] Volver a lista de wallets → P&L del icono DEBE ser $94.58K (igual)
- [ ] Cambiar "Data Range" a 30 días → P&L, Trades, Buy/Sell DEBEN cambiar
- [ ] Revisar logs de Celery para detectar warnings de duplicados

### Valores de prueba:
```
Wallet con:
- 10 BUYs ($100 total)
- 5 SELLs ($60 total)
- 3 REDEEMs ($30 total)

P&L esperado: ($60 + $30) - $100 = -$10
```

---

## Archivos Modificados

| Archivo | Cambio Principal | Estado |
|---------|------------------|--------|
| `wallet_analysis/pnl_calculator.py` | Re-export desde calculators | ✓ |
| `wallet_analysis/calculators/*` | Nueva estructura SOLID | ✓ |
| `src/services/trade_service.py` | Eliminar REDEEM→Trade, usar Decimal | ✓ |
| `src/api/models.py` | Usar Decimal, agregar to_decimal() | ✓ |
| `wallet_analysis/views.py` | Unificar fuente P&L, cache sync, filtro fecha | ✓ |
| `wallet_analysis/tasks.py` | Usar pnl_calculator para guardar P&L | ✓ |
| `wallet_analysis/models.py` | Mejorar constraint unicidad | ✓ |
| `wallet_analysis/services.py` | Agregar logging, detectar duplicados | ✓ |
| `wallet_analysis/migrations/0004_*` | Migración constraint | ✓ |

---

## Review

### Cambios Arquitecturales

1. **Fuente única de verdad para P&L:** `wallet_analysis/calculators/pnl_calculator.py`
   - Fórmula: `P&L = (sells + redeems + merges + rewards) - (buys + splits)`
   - Usa datos de tablas Trade + Activity

2. **Separación de responsabilidades:**
   - `Trade` table: Solo BUY/SELL trades
   - `Activity` table: REDEEM, SPLIT, MERGE, REWARD
   - `pnl_calculator`: Combina ambos para P&L

3. **Precisión decimal:** Todos los valores numéricos se parsean con `Decimal(str(value))`

4. **SOLID aplicado:**
   - SRP: Cada clase tiene una responsabilidad
   - OCP: Extensible via agregadores
   - DIP: Depende de interfaces, no implementaciones

5. **Sincronización caché:** El endpoint /stats/ actualiza `wallet.subgraph_realized_pnl`
   cuando calcula P&L completo, manteniendo la lista sincronizada con el detalle.

6. **Filtro de tiempo funcional:** El "Data Range" ahora afecta:
   - P&L total
   - Conteo de trades (Total Trades, Buys, Sells)
   - Gráficos
   - Activities por tipo

### Fix Aplicado: float vs Decimal en Analytics

**Problema:** Error en Celery task: `unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`

**Causa:** El modelo Trade usa Decimal pero analytics_service.py y copy_trading_analyzer.py usaban literales float.

**Solución:** Convertir a float() explícitamente en los servicios de análisis (no son fuente de verdad para P&L).

**Archivos modificados:**
- `src/services/analytics_service.py` (líneas 177-180, 210-212, 278, 310)
- `src/services/copy_trading_analyzer.py` (líneas 165, 202-220, 285)

### Próximos pasos

1. Ejecutar migración: `python manage.py migrate`
2. Hacer refresh de wallets existentes para recalcular P&L
3. Verificar que los datos históricos migran correctamente

---

## Fix 10 Bugs: Trades y P&L (2026-02-07)

### Estado: COMPLETADO ✓

| Bug | Severidad | Descripción | Archivo(s) | Estado |
|-----|-----------|-------------|------------|--------|
| BUG 1 | HIGH | end_date pierde último día en Celery tasks | `tasks.py` | ✓ |
| BUG 2 | HIGH | calculate_filtered() devuelve pnl_by_market sin filtrar | `calculators/pnl_calculator.py` | ✓ |
| BUG 3 | HIGH | Constraint unique_activity sin wallet | `models.py`, migración 0005 | ✓ |
| BUG 4 | HIGH | Sin límite de iteraciones en paginación | `polymarket_client.py` | ✓ |
| BUG 5 | MEDIUM | Conteo de actividades insertadas inflado | `services.py` | ✓ |
| BUG 6 | MEDIUM | Dedup key inconsistente en fetch_all_trades | `polymarket_client.py` | ✓ |
| BUG 7 | MEDIUM | CONVERSION ignorado en cálculo P&L | `aggregators.py`, `pnl_calculator.py`, `trade_service.py`, `polymarket_client.py` | ✓ |
| BUG 8 | LOW | Off-by-one en cursor de timestamp | `polymarket_client.py` (documentado) | ✓ |
| BUG 9 | LOW | Parse de fechas falla silenciosamente | `views.py` | ✓ |
| BUG 10 | LOW | Nulls inconsistentes en analysis_metrics | `views.py` | ✓ |

### Archivos nuevos
- `wallet_analysis/migrations/0005_update_activity_unique_constraint.py`

### Verificación pendiente
- [ ] `python manage.py migrate` — aplicar migración 0005
- [ ] Verificar pnl_by_market filtrado correctamente
- [ ] Verificar CONVERSION aparece en fetch de actividades
- [ ] Verificar loops de paginación respetan MAX_PAGINATION_ITERATIONS

---

## Optimización de Cuellos de Botella en BD (2026-02-11)

### Estado: COMPLETADO ✓

### Cambios realizados

| # | Severidad | Optimización | Archivo | Estado |
|---|-----------|-------------|---------|--------|
| 1 | CRITICAL | Eliminar COUNT queries en save_trades() y save_activities() | `services.py` | ✓ |
| 2 | HIGH | bulk_create en save_positions_from_subgraph() | `services.py` | ✓ |
| 3 | HIGH | bulk_create + market_cache en save_current_positions() | `services.py` | ✓ |
| 4 | HIGH | Eliminar doble carga en calculate_filtered() | `calculators/pnl_calculator.py` | ✓ |
| 5 | MEDIUM | Batch market lookup en stats view (in_bulk) | `views.py` | ✓ |
| 6 | LOW-MEDIUM | Bulk update/create en save_market_resolutions() | `services.py` | ✓ |
| 7 | INFRA | PostgreSQL config + docker-compose | `settings.py`, `docker-compose.yml` | ✓ |

### Verificación
- [x] 14/14 tests passing (`python manage.py test wallet_analysis`)

### Impacto estimado
- **save_trades()**: Eliminados 2 COUNT queries por batch (O(N) cada uno). Para wallet con 50K trades + 10K nuevos: ~200 COUNT queries eliminados.
- **save_activities()**: Mismo patrón, COUNT eliminados por batch.
- **save_positions/current_positions**: N creates individuales → 1 bulk_create.
- **save_market_resolutions()**: N update_or_create → 1 SELECT + 1 bulk_update + 1 bulk_create.
- **calculate_filtered()**: 4 DB queries (2x trades + 2x activities) → 2 DB queries.
- **stats view market lookup**: N queries → 1 query con in_bulk().

---

## Migrate PnL to Weighted Average Cost Basis (2026-02-14)

### Estado: COMPLETADO ✓

### Resumen
Migrated from cash flow P&L (inflows - outflows) to weighted average cost basis (WACB), the industry standard used by Polymarket's Data API, PnL subgraph, and community tools. This enables per-position tracking, realized/unrealized PnL separation, and results that match Polymarket's UI.

### Fases

| # | Fase | Estado |
|---|------|--------|
| 1 | Add `asset`/`outcome` to Activity model | ✓ |
| 2 | Core Position Tracker Engine (pure logic) | ✓ |
| 3 | Cost Basis Calculator + Aggregators | ✓ |
| 4 | Wire into existing system | ✓ |
| 5 | Tests (14 existing + 16 new = 30 total) | ✓ |

### Archivos nuevos
- `wallet_analysis/calculators/position_tracker.py` — PositionState, RealizedPnLEvent, PositionTracker
- `wallet_analysis/calculators/cost_basis_calculator.py` — CostBasisPnLCalculator
- `wallet_analysis/calculators/cost_basis_aggregators.py` — CostBasisMarketAggregator, CostBasisDailyAggregator
- `wallet_analysis/migrations/0007_add_asset_outcome_to_activity.py`

### Archivos modificados
- `wallet_analysis/models.py` — Added `asset`, `outcome` to Activity
- `wallet_analysis/services.py` — Persist `asset`/`outcome` in save_activities()
- `wallet_analysis/calculators/interfaces.py` — Added IPositionTracker
- `wallet_analysis/calculators/pnl_calculator.py` — Added CashFlowPnLCalculator alias, cost basis default
- `wallet_analysis/calculators/__init__.py` — Export new classes
- `wallet_analysis/pnl_calculator.py` — Re-export new functions
- `wallet_analysis/views.py` — Added unrealized_pnl, total_pnl, cash_flow_pnl, positions to response
- `wallet_analysis/tasks.py` — Updated comment (import unchanged)
- `wallet_analysis/tests.py` — 16 new tests for position tracker, cost basis calc, method comparison

### Verificación
- [x] All 30 tests pass (14 existing + 16 new)
- [ ] Run migration: `python manage.py migrate`
- [ ] Re-fetch a wallet to populate `asset`/`outcome` on activities
- [ ] Compare cash_flow_pnl vs cost_basis realized_pnl for known wallets
- [ ] Spot-check against Polymarket UI for a wallet with known positions
