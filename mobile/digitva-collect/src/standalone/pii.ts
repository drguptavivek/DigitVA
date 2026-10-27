/**
 * Payload fields that carry personal data, for the standalone export's "omit identifiers" option.
 * Mirrors PII_FIELDS in app/services/pii_field_registry.py plus the identity and attachment-slot ids in
 * CSV_EXPORT_OMIT_PAYLOAD_FIELDS (app/services/data_management_service.py); the server lists are the source,
 * so change them there first and copy the ids here.
 */
export const PII_FIELD_IDS: ReadonlySet<string> = new Set([
  "Id10007", "Id10010", "Id10010a", "Id10010b", "Id10010c", "Id10017", "Id10018", "Id10055", "Id10057",
  "Id10061", "Id10062", "Id10070", "Id10071", "Id10072", "Id10073", "visit_address", "visit_remarks",
  "abha_number", "abha_address",
  "unique_id", "unique_id2", "instanceName", "SubmitterName", "Id10476_audio", "imagenarr",
  ...Array.from({ length: 30 }, (_, i) => `md_im${i + 1}`),
  ...Array.from({ length: 5 }, (_, i) => `ds_im${i + 1}`),
]);
