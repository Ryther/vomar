#ifndef VIMAR_CONNECTION_INTENT_H
#define VIMAR_CONNECTION_INTENT_H
/* A dedicated settings key: never delete application settings or Bluetooth bonds. */
enum connection_intent {CONNECTION_INITIAL=0,CONNECTION_REQUESTED=1,CONNECTION_ATTEMPTED=2};
int connection_intent_load(void);
int connection_intent_request(void);
int connection_intent_claim(void);
#endif
