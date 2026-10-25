package org.openvimar.updater

import android.app.Activity
import android.content.res.ColorStateList
import android.view.MotionEvent
import android.view.View
import android.widget.*
import androidx.core.view.ViewCompat

/** One native list for touch forwarding, tap, keyboard and accessibility. */
internal class DeviceFilterPopup(private val activity:Activity,private val anchor:Button,
    private val options:List<String>,private val selected:()->Int,private val choose:(Int)->Unit) {
    private val popup=ListPopupWindow(activity).apply {
        anchorView=anchor;isModal=true;inputMethodMode=ListPopupWindow.INPUT_METHOD_NOT_NEEDED
        setBackgroundDrawable(NativeUi.shape(activity,activity.getColor(R.color.ui_panel),stroke=activity.getColor(R.color.ui_outline)))
        setAdapter(object:ArrayAdapter<String>(activity,android.R.layout.simple_list_item_single_choice,options){
            override fun getView(position:Int,convertView:View?,parent:android.view.ViewGroup):View =
                (super.getView(position,convertView,parent) as CheckedTextView).apply {
                    textSize=15f;setTextColor(activity.getColor(R.color.ui_text));minHeight=NativeUi.dp(activity,48)
                    setPadding(NativeUi.dp(activity,16),NativeUi.dp(activity,12),NativeUi.dp(activity,16),NativeUi.dp(activity,12))
                    setSingleLine(false);checkMarkTintList=ColorStateList.valueOf(activity.getColor(R.color.ui_primary));isChecked=position==selected()
                }
        })
        setOnItemClickListener{_,_,position,_->dismiss();choose(position)}
        setOnDismissListener{ViewCompat.setStateDescription(anchor,"Collapsed");if(anchor.isAttachedToWindow)anchor.requestFocus()}
    }
    @android.annotation.SuppressLint("ClickableViewAccessibility")
    // Non-forwarded taps return to Button.onTouchEvent/performClick. Forwarded
    // gestures use the same native accessible ListView item click actions.
    private fun attach(){
        ViewCompat.setStateDescription(anchor,"Collapsed")
        anchor.contentDescription="Filter devices: ${options[selected()]}. Choose a device filter."
        anchor.setOnClickListener{show()}
        val forwarding=popup.createDragToOpenListener(anchor)
        anchor.setOnTouchListener{view,event->
            if(event.actionMasked==MotionEvent.ACTION_DOWN)show()
            val handled=forwarding.onTouch(view,event)
            if(event.actionMasked==MotionEvent.ACTION_CANCEL)popup.dismiss()
            handled
        }
        // Native forwarding owns movement/slop and the original pointer stream;
        // opening on DOWN removes the extra tap/hold stage, rather than replaying touches.
        anchor.addOnAttachStateChangeListener(object:View.OnAttachStateChangeListener{
            override fun onViewAttachedToWindow(v:View){}
            override fun onViewDetachedFromWindow(v:View){popup.dismiss()}
        })
    }
    init {attach()}
    private fun show(){if(!anchor.isAttachedToWindow)return;popup.width=anchor.width;popup.show();popup.listView?.apply{choiceMode=ListView.CHOICE_MODE_SINGLE;setItemChecked(selected(),true)};ViewCompat.setStateDescription(anchor,"Expanded")}
}
