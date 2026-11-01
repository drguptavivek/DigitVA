// The encrypted buffer, re-exported from inside the project so a dynamic import() of it gets a split bundle
// Metro's dev server can serve: a split of the file outside the project root itself is requested as
// /app/static/..., which the same-origin Flask app answers.
export { createBuffer, createIdbBacking } from "../../../../app/static/js/intake/attachment_buffer.js";
