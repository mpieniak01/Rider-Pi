import { catalogKnown, fresh } from './model.js';
export function serviceActionBlock(row, action, { catalog, services, busy, safety }) {
  if (!catalogKnown(catalog) || services?.contract_version !== 2 || !fresh(services, 10)) return 'service_data_unavailable';
  if (!fresh(row, 10) || row.error || (row.load_state ?? row.load) !== 'loaded') return row.error || 'service_not_loaded_or_stale';
  if (busy.has(row.unit)) return 'operation_pending';
  const permission = row.permissions?.[action];
  if (permission?.allowed !== true) return permission?.reason || 'permission_unknown';
  if (['start', 'restart'].includes(action)) {
    if (typeof row.can_move !== 'boolean') return 'movement_effect_unknown';
    if (row.start_available === false) return row.start_unavailable_reason || 'start_unavailable';
    if (row.can_move && (!safety.can(row.motion_owner) || !safety.can(row.motion_owner, 'turn'))) return 'motion_authorization_required';
  }
  return null;
}
