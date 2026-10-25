package org.openvimar.updater

import android.content.Context
import android.content.res.Configuration
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

/** Shared native expression of the approved fleet prototype, including dialogs
 * and diagnostics. State, transport authority and content stay with callers. */
internal object NativeUi {
    fun themedContext(base:Context):Context {
        val theme=base.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE).getString("theme","System")
        if(theme!="Light"&&theme!="Dark")return base
        return base.createConfigurationContext(Configuration(base.resources.configuration).apply {
            uiMode=(uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or
                if(theme=="Dark")Configuration.UI_MODE_NIGHT_YES else Configuration.UI_MODE_NIGHT_NO
        })
    }
    @Suppress("DEPRECATION")
    fun systemBars(activity:android.app.Activity) {
        val dark=activity.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK==Configuration.UI_MODE_NIGHT_YES
        val appearance=androidx.core.view.WindowCompat.getInsetsController(activity.window,activity.window.decorView)
        appearance.isAppearanceLightStatusBars=!dark
        appearance.isAppearanceLightNavigationBars=!dark
        activity.window.statusBarColor=activity.getColor(R.color.ui_surface)
        activity.window.navigationBarColor=activity.getColor(R.color.ui_surface)
    }
    fun insets(view:android.view.View){
        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(view){root,insets->
            val safe=insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars() or androidx.core.view.WindowInsetsCompat.Type.displayCutout() or androidx.core.view.WindowInsetsCompat.Type.ime())
            root.setPadding(safe.left,safe.top,safe.right,safe.bottom);insets
        }
        view.addOnAttachStateChangeListener(object:android.view.View.OnAttachStateChangeListener{
            override fun onViewAttachedToWindow(v:android.view.View){androidx.core.view.ViewCompat.requestApplyInsets(v)}
            override fun onViewDetachedFromWindow(v:android.view.View){}
        })
    }
    fun dp(context:Context,value:Int)=(value*context.resources.displayMetrics.density+.5f).toInt()
    fun shape(context:Context,fill:Int,radius:Int=8,stroke:Int?=null,width:Int=1)=GradientDrawable().apply {
        setColor(fill);cornerRadius=dp(context,radius).toFloat()
        stroke?.let {setStroke(dp(context,width),it)}
    }
    private fun states(context:Context,filled:Boolean,outline:Boolean,selected:Boolean=false):Drawable {
        fun color(id:Int)=context.getColor(id)
        fun surface(focused:Boolean)=shape(context,
            if(filled)color(R.color.ui_primary) else if(selected)color(R.color.ui_panel) else android.graphics.Color.TRANSPARENT,
            stroke=if(focused)color(R.color.ui_primary) else if(outline)color(R.color.ui_outline) else null,
            width=if(focused)2 else 1)
        val drawable=StateListDrawable().apply {
            addState(intArrayOf(-android.R.attr.state_enabled),shape(context,color(R.color.ui_disabled)))
            addState(intArrayOf(android.R.attr.state_focused),surface(true))
            addState(intArrayOf(),surface(false))
        }
        val tint=color(R.color.ui_primary)
        return RippleDrawable(ColorStateList.valueOf((tint and 0xffffff) or 0x22000000),drawable,shape(context,-1))
    }
    fun button(context:Context,label:String,filled:Boolean=false,outline:Boolean=false,action:()->Unit)=Button(context).apply {
        text=label;isAllCaps=false;gravity=Gravity.CENTER;minHeight=dp(context,48);minimumHeight=dp(context,48)
        minWidth=0;minimumWidth=0;setPadding(dp(context,16),dp(context,10),dp(context,16),dp(context,10))
        textSize=15f;includeFontPadding=false;setLineSpacing(dp(context,2).toFloat(),1f)
        typeface=Typeface.create(if(filled)"sans-serif-medium" else "sans-serif",Typeface.NORMAL)
        stateListAnimator=null;background=states(context,filled,outline);backgroundTintList=null
        setTextColor(ColorStateList(arrayOf(intArrayOf(android.R.attr.state_enabled),intArrayOf()),
            intArrayOf(context.getColor(if(filled)R.color.ui_on_primary else R.color.ui_primary),context.getColor(R.color.ui_on_disabled))))
        setOnClickListener {action()}
    }
    fun label(context:Context,value:String,size:Int=15,strong:Boolean=false,secondary:Boolean=false)=TextView(context).apply {
        text=value;textSize=size.toFloat();includeFontPadding=false
        typeface=Typeface.create(if(strong)"sans-serif-medium" else "sans-serif",Typeface.NORMAL)
        setTextColor(context.getColor(if(secondary)R.color.ui_text_secondary else R.color.ui_text))
        setLineSpacing(dp(context,3).toFloat(),1f)
    }
    enum class Input { TEXT, SEARCH, ADDRESS, IDENTIFIER, USERNAME, PASSWORD }
    fun field(context:Context,hintText:String,value:String="",singleLine:Boolean=true,input:Input=Input.TEXT)=EditText(context).apply {
        hint=hintText;contentDescription=hintText;setText(value);setSingleLine(singleLine)
        inputType=when(input){
            Input.TEXT -> android.text.InputType.TYPE_CLASS_TEXT
            Input.SEARCH -> android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            Input.ADDRESS -> android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_URI or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            Input.IDENTIFIER,Input.USERNAME -> android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            Input.PASSWORD -> android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        if(input!=Input.TEXT)imeOptions=imeOptions or android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        if(input==Input.SEARCH)imeOptions=imeOptions or android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH
        setSingleLine(singleLine)
        // setSingleLine installs its own transformation; restore password masking last.
        if(input==Input.PASSWORD)transformationMethod=android.text.method.PasswordTransformationMethod.getInstance()
        typeface=Typeface.create("sans-serif",Typeface.NORMAL)
        textSize=15f;minHeight=dp(context,48);minimumHeight=dp(context,48)
        setTextColor(context.getColor(R.color.ui_text));setHintTextColor(context.getColor(R.color.ui_text_secondary))
        setPadding(dp(context,12),dp(context,12),dp(context,12),dp(context,12))
        background=StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused),shape(context,context.getColor(R.color.ui_surface),stroke=context.getColor(R.color.ui_primary),width=2))
            addState(intArrayOf(),shape(context,context.getColor(R.color.ui_surface),stroke=context.getColor(R.color.ui_outline)))
        }
        backgroundTintList=null
    }
    fun status(context:Context,value:String="")=label(context,value,16).apply {
        accessibilityLiveRegion=android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE
        setPadding(dp(context,16),dp(context,14),dp(context,16),dp(context,14))
        background=shape(context,context.getColor(R.color.ui_panel),10)
    }
    fun taskHeader(context:Context,title:String,onBack:()->Unit)=android.widget.LinearLayout(context).apply {
        gravity=Gravity.CENTER_VERTICAL
        addView(iconButton(context,"back","Back",onBack),android.widget.LinearLayout.LayoutParams(dp(context,48),dp(context,48)))
        addView(label(context,title,24,true).also{androidx.core.view.ViewCompat.setAccessibilityHeading(it,true)},android.widget.LinearLayout.LayoutParams(0,-2,1f))
    }
    fun disclosure(context:Context,collapsedLabel:String,expandedLabel:String,content:android.view.View,expanded:Boolean=false,onChanged:(Boolean)->Unit={}):Button {
        content.visibility=if(expanded)android.view.View.VISIBLE else android.view.View.GONE
        return button(context,if(expanded)expandedLabel else collapsedLabel){}.apply {
            isActivated=expanded;gravity=Gravity.START or Gravity.CENTER_VERTICAL
            fun describe(){androidx.core.view.ViewCompat.setStateDescription(this,if(isActivated)"Expanded" else "Collapsed")}
            describe()
            setOnClickListener{
                isActivated=!isActivated;content.visibility=if(isActivated)android.view.View.VISIBLE else android.view.View.GONE
                text=if(isActivated)expandedLabel else collapsedLabel;describe();onChanged(isActivated)
            }
        }
    }
    fun navigation(context:Context,view:Button,name:String,selected:Boolean) {
        val color=context.getColor(if(selected)R.color.ui_primary else R.color.ui_text_secondary)
        val fill=if(selected)context.getColor(R.color.ui_panel)else android.graphics.Color.TRANSPARENT
        val surface=StateListDrawable().apply{
            addState(intArrayOf(android.R.attr.state_focused),shape(context,fill,stroke=context.getColor(R.color.ui_primary),width=2))
            addState(intArrayOf(),shape(context,fill))
        }
        view.background=RippleDrawable(ColorStateList.valueOf((color and 0xffffff)or 0x22000000),surface,shape(context,-1))
        view.backgroundTintList=null;view.background.state=view.drawableState;view.setTextColor(color)
        view.setCompoundDrawablesWithIntrinsicBounds(null,Icon(context,name,color,22),null,null)
        view.compoundDrawablePadding=dp(context,4);view.textSize=12f
        view.setPadding(dp(context,8),dp(context,8),dp(context,8),dp(context,8));view.minimumHeight=dp(context,64)
        view.typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)
    }
    fun iconButton(context:Context,name:String,label:String,action:()->Unit)=button(context,"",action=action).apply {
        contentDescription=label;tooltipText=label;setPadding(dp(context,12),dp(context,12),dp(context,12),dp(context,12))
        setCompoundDrawablesWithIntrinsicBounds(Icon(context,name,context.getColor(R.color.ui_primary),22),null,null,null)
    }
    class Icon(context:Context,name:String,color:Int,size:Int=22):Drawable() {
        private val pixels=dp(context,size)
        private val path=Path().apply {
            fun line(x:Float,y:Float,x2:Float,y2:Float){moveTo(x,y);lineTo(x2,y2)}
            when(name) {
                "devices"->{for(x in listOf(3f,14f)){addRect(x,4f,x+7,11f,Path.Direction.CW);addRect(x,15f,x+7,21f,Path.Direction.CW)}}
                "activity"->{for(y in listOf(4f,12f,20f)){line(7f,y,21f,y);line(2f,y,3f,y)}}
                "settings"->{for(y in listOf(6f,12f,18f))line(4f,y,20f,y);line(8f,3f,8f,9f);line(16f,9f,16f,15f);line(10f,15f,10f,21f)}
                "back"->{moveTo(15f,5f);lineTo(8f,12f);lineTo(15f,19f)}
                "plus"->{line(12f,4f,12f,20f);line(4f,12f,20f,12f)}
                "down"->{moveTo(5f,9f);lineTo(12f,16f);lineTo(19f,9f)}
                "search"->{addCircle(10f,10f,7f,Path.Direction.CW);line(15f,15f,21f,21f)}
                else->{moveTo(9f,5f);lineTo(16f,12f);lineTo(9f,19f)}
            }
        }
        private val paint=Paint(Paint.ANTI_ALIAS_FLAG).apply {this.color=color;style=Paint.Style.STROKE;strokeWidth=1.7f;strokeCap=Paint.Cap.ROUND;strokeJoin=Paint.Join.ROUND}
        override fun draw(canvas:Canvas) {val save=canvas.save();canvas.translate(bounds.left.toFloat(),bounds.top.toFloat());canvas.scale(bounds.width()/24f,bounds.height()/24f);canvas.drawPath(path,paint);canvas.restoreToCount(save)}
        override fun getIntrinsicWidth()=pixels
        override fun getIntrinsicHeight()=pixels
        override fun setAlpha(alpha:Int){paint.alpha=alpha;invalidateSelf()}
        override fun setColorFilter(filter:ColorFilter?){paint.colorFilter=filter;invalidateSelf()}
        @Deprecated("Drawable opacity") override fun getOpacity()=PixelFormat.TRANSLUCENT
    }
}
