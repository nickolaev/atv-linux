#ifndef ATV_AUTH_H
#define ATV_AUTH_H
/* Pin a 32-byte random secret on both hosts. The caller MUST authenticate a
 * canonical, versioned manifest containing a fresh session nonce, unique job
 * ID, operation, payload byte length and SHA-256 digest; reject replay and
 * verify the actual payload digest before execution. Secret HMAC does not
 * encrypt jobs/logs, nor authenticate the report endpoint. */
#define ATV_AUTH_MAX_MESSAGE 1024u
struct atv_sha256 { unsigned int h[8], used; unsigned long long total; unsigned char tail[64]; };
void atv_sha256_init(struct atv_sha256 *ctx);
void atv_sha256_update(struct atv_sha256 *ctx, const unsigned char *data, unsigned int len);
void atv_sha256_final(struct atv_sha256 *ctx, unsigned char out[32]);
void atv_hmac_init(struct atv_sha256 *ctx, const unsigned char key[32]);
void atv_hmac_final(struct atv_sha256 *ctx, const unsigned char key[32], unsigned char out[32]);
int atv_auth_verify(const unsigned char key[32], const unsigned char *message, unsigned int length, const unsigned char tag[32]);
void atv_auth_sha256(const unsigned char *data, unsigned int length, unsigned char out[32]);
#endif
