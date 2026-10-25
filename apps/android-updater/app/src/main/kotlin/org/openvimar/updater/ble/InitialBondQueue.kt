package org.openvimar.updater.ble

import java.util.Deque

/** One explicit initial bond, after LE discovery and before the SMP init queue. */
internal class InitialBondQueue {
 private var requested=false
 @Synchronized fun <T> prepare(state:BondState,create:()->T):Deque<T>? {
  if(state!=BondState.NONE||requested)return null
  requested=true
  return java.util.ArrayDeque<T>().apply{addLast(create())}
 }
}
