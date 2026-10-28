#include <jni.h>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

extern "C" {
const char* smartva_version(void);
int smartva_score_json(const char*, const char*, int, int, int, int, int, char**, char**);
void smartva_free_string(char*);
}

namespace {
constexpr size_t MAX_REQUEST_BYTES = 1024 * 1024;
constexpr size_t MAX_REPLY_BYTES = 2 * 1024 * 1024;

std::vector<char> utf8Bytes(JNIEnv* env, jstring value) {
  jclass stringClass = env->FindClass("java/lang/String");
  jmethodID getBytes = env->GetMethodID(stringClass, "getBytes", "(Ljava/lang/String;)[B");
  jstring charset = env->NewStringUTF("UTF-8");
  auto bytes = static_cast<jbyteArray>(env->CallObjectMethod(value, getBytes, charset));
  env->DeleteLocalRef(charset);
  if (!bytes || env->ExceptionCheck()) return {};
  const jsize length = env->GetArrayLength(bytes);
  std::vector<char> result(static_cast<size_t>(length) + 1, '\0');
  if (length > 0) env->GetByteArrayRegion(bytes, 0, length, reinterpret_cast<jbyte*>(result.data()));
  env->DeleteLocalRef(bytes);
  return env->ExceptionCheck() ? std::vector<char>() : result;
}

jstring fromUtf8(JNIEnv* env, const char* value, size_t length) {
  jclass stringClass = env->FindClass("java/lang/String");
  jmethodID constructor = env->GetMethodID(stringClass, "<init>", "([BLjava/lang/String;)V");
  jbyteArray bytes = env->NewByteArray(static_cast<jsize>(length));
  if (!bytes) return nullptr;
  env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(length), reinterpret_cast<const jbyte*>(value));
  jstring charset = env->NewStringUTF("UTF-8");
  jobject result = env->NewObject(stringClass, constructor, bytes, charset);
  env->DeleteLocalRef(bytes);
  env->DeleteLocalRef(charset);
  return static_cast<jstring>(result);
}

jstring status(JNIEnv* env, const char* text) {
  return fromUtf8(env, text, std::strlen(text));
}
}  // namespace

extern "C" JNIEXPORT jstring JNICALL
Java_expo_modules_digitvasmartva_SmartVaJni_version(JNIEnv* env, jobject) {
  const char* version = smartva_version();
  return version ? status(env, version) : nullptr;
}

extern "C" JNIEXPORT jstring JNICALL
Java_expo_modules_digitvasmartva_SmartVaJni_scoreJson(
    JNIEnv* env, jobject, jstring payload, jstring country, jint hiv, jint malaria, jint hce, jint freetext) {
  auto payloadBytes = utf8Bytes(env, payload);
  auto countryBytes = utf8Bytes(env, country);
  if (payloadBytes.empty() || countryBytes.empty() || payloadBytes.size() - 1 > MAX_REQUEST_BYTES) {
    return status(env, "TOO_LARGE");
  }

  char* result = nullptr;
  char* error = nullptr;
  const int code = smartva_score_json(
      payloadBytes.data(), countryBytes.data(), hiv, malaria, hce, freetext, 0, &result, &error);
  if (error) smartva_free_string(error);
  if (code != 0 || !result) {
    if (result) smartva_free_string(result);
    return status(env, "ENGINE_ERROR");
  }

  const size_t length = std::strlen(result);
  if (length > MAX_REPLY_BYTES) {
    smartva_free_string(result);
    return status(env, "TOO_LARGE");
  }
  jstring reply = fromUtf8(env, result, length);
  smartva_free_string(result);
  return reply;
}
