/* Keep the48KiB physical partition/protection and application addresses fixed.
 * _flash_used includes ROM load images of initialized data and RAM functions.
 * No actual anchor bytes are linked: the owner's future initial SWD writes data.
 */
ASSERT(_flash_used <= 0xb000, "Common restore gate code/ROM data overlaps reserved anchor page")
