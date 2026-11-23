import { useLocalSearchParams } from "expo-router";

import Register from "./register";
import SupervisorDeathEdit, { SUPERVISOR_EDIT } from "./supervisorDeathEdit";

/** /register: the interviewer's registration form, or (`by=supervisor`) a supervisor's online correction of a death report. */
export default function RegisterRoute() {
  const { by } = useLocalSearchParams<{ by?: string }>();
  return by === SUPERVISOR_EDIT ? <SupervisorDeathEdit /> : <Register />;
}
