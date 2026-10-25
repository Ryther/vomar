package org.openvimar.updater.ble

import io.runtime.mcumgr.util.CBOR
import io.runtime.mcumgr.McuMgrScheme
import io.runtime.mcumgr.response.McuMgrResponse
import org.junit.Assert.*
import org.junit.Test

class RecoveryBootHistoryCodecTest {
 private fun state()=linkedMapOf<String,Any>("initialized" to true,"loaded_valid" to false,"storage_valid" to true,"load_rc" to -2,"decode_rc" to -2147483648L,"save_rc" to 2147483647L,"view_rc" to 0)
 private fun entry()=linkedMapOf<String,Any>("seq" to 4294967295L,"image" to 1,"reason" to 7,"raw_reset_flags" to 4294967295L)
 private fun valid()=linkedMapOf<String,Any>("protocol" to 1,"record_size" to 88,"capacity" to 6,"current_image" to 1,"sequence" to 4294967295L,"pending_reason" to 0,"state" to state(),"entries" to List(6){entry()})
 @Test fun exactFirmwareSchemaAcceptsSixEntriesSignedResultsAndUnsignedWords() {
  val result=RecoveryBootHistoryCodec.decode(CBOR.toBytes(valid()))
  assertEquals(6,result.entries.size);assertEquals(-2147483648,result.state.decodeRc);assertEquals(4294967295L,result.entries[0].rawResetFlags)
 }
 @Test fun coercionsUnknownFieldsAndOutOfRangeRecordsAreRejected() {
  val cases=mutableListOf<Map<String,Any>>()
  for(value in listOf<Any>(true,"1",1.0,-1L))cases+=valid().also{it["protocol"]=value}
  cases+=valid().also{it["extra"]=0};cases+=valid().also{it["entries"]=List(7){entry()}}
  cases+=valid().also{it["state"]=state().also{s->s["initialized"]=1}}
  cases+=valid().also{it["state"]=state().also{s->s["load_rc"]=-2147483649L}}
  cases+=valid().also{it["entries"]=listOf(entry().also{e->e["raw_reset_flags"]=-1})}
  cases+=valid().also{it["entries"]=listOf(entry().also{e->e["reason"]=8})}
  for(map in cases)assertThrows(Exception::class.java){RecoveryBootHistoryCodec.decode(CBOR.toBytes(map))}
 }
 @Test fun rawDuplicateTrailingTruncatedAndDeepCborNeverAccepted() {
  val payload=CBOR.toBytes(valid())
  for(bytes in listOf(payload+byteArrayOf(0),payload.copyOf(payload.size-1),byteArrayOf(0xa2.toByte(),0x61,0x61,0x01,0x61,0x61,0x02),ByteArray(1025),byteArrayOf(0x9f.toByte(),0x9f.toByte(),0x9f.toByte(),0x9f.toByte(),0x01,0xff.toByte(),0xff.toByte(),0xff.toByte(),0xff.toByte())))
   assertThrows(Exception::class.java){RecoveryBootHistoryCodec.decode(bytes)}
 }
 @Test fun addingSignedHistorySupportDoesNotWidenIdentityCborContract() {
  assertThrows(IllegalArgumentException::class.java){StrictSmpCbor.decode(CBOR.toBytes(mapOf("protocol" to -1)))}
 }
 @Test fun actualSmpResponseChecksHistoryGroupHeaderAndExactUnsupportedReply() {
  fun response(payload:ByteArray,group:Int=0x8041):RecoveryBootHistoryResponse {
   val header=byteArrayOf(9,0,(payload.size shr 8).toByte(),payload.size.toByte(),(group shr 8).toByte(),group.toByte(),0,0)
   return McuMgrResponse.buildResponse(McuMgrScheme.BLE,header+payload,RecoveryBootHistoryResponse::class.java)
  }
  assertEquals(6,response(CBOR.toBytes(valid())).history().entries.size)
  assertThrows(IllegalArgumentException::class.java){response(CBOR.toBytes(valid()),0x8040).history()}
  assertTrue(response(CBOR.toBytes(mapOf("rc" to 8))).rejection() is org.openvimar.updater.core.BootHistoryUnavailable)
  assertThrows(IllegalArgumentException::class.java){response(CBOR.toBytes(mapOf("rc" to "8"))).validateWire()}
 }
}
