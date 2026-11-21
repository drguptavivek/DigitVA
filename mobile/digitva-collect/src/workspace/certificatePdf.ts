/** Web: the certificate opens the server page instead (CertificateButton), so there is nothing to print here. */
export async function sharePdf(_html: string, _name: string): Promise<void> {
  throw new Error("certificate_pdf_native_only");
}
