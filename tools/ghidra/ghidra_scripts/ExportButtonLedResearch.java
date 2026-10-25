// @category Vimar30805
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.nio.file.*;
public class ExportButtonLedResearch extends GhidraScript {
 public void run() throws Exception {
  Path out=Path.of(getScriptArgs()[0]); Files.createDirectories(out);
  DecompInterface d=new DecompInterface();d.openProgram(currentProgram);
  FunctionIterator fs=currentProgram.getFunctionManager().getFunctions(true);
  while(fs.hasNext()){Function f=fs.next();long a=f.getEntryPoint().getOffset();
   if(!((a>=0x47000&&a<0x4f800)||(a>=0x44000&&a<0x45c00)||(a==0x2cd94)))continue;
   DecompileResults r=d.decompileFunction(f,45,monitor);
   String s=r.decompileCompleted()?r.getDecompiledFunction().getC():r.getErrorMessage();
   Files.writeString(out.resolve(String.format("%08x.c",a)),s);
  }
  StringBuilder b=new StringBuilder();
  for(long a=0x48000;a<0x4f800;a+=4){b.append(String.format("%08x %08x%n",a,currentProgram.getMemory().getInt(toAddr(a))));}
  Files.writeString(out.resolve("literal-words.txt"),b);d.dispose();
 }
}
