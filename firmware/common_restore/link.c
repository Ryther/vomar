/* SPDX-License-Identifier: Apache-2.0 */
#include "link.h"
uint32_t common_restore_link_connect(struct common_restore_link *s)
{if(s->connected)return 0;s->generation++;if(!s->generation)s->generation++;s->owner=s->generation;s->connected=true;s->published_owner=0;return s->owner;}
bool common_restore_link_disconnect(struct common_restore_link *s,uint32_t owner)
{if(!s->connected||owner!=s->owner)return false;s->connected=false;s->published_owner=0;return true;}
void common_restore_link_publish(struct common_restore_link *s,uint32_t owner)
{s->published_owner=s->connected&&owner==s->owner?owner:0;}
bool common_restore_link_needs_open(const struct common_restore_link *s,bool quiescing)
{return s->connected&&!s->busy&&!quiescing&&s->published_owner!=s->owner;}
bool common_restore_link_submit(struct common_restore_link *s,uint32_t owner,bool quiescing)
{if(!s->connected||s->busy||quiescing||owner!=s->owner||owner!=s->published_owner)return false;s->busy=true;s->pending_owner=owner;return true;}
bool common_restore_link_finish(struct common_restore_link *s,uint32_t owner)
{if(!s->busy||s->pending_owner!=owner)return false;s->busy=false;s->pending_owner=0;return true;}
