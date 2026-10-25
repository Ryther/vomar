// Export deterministic import and entry-point metadata.
// @category Vimar30805

import ghidra.app.script.GhidraScript;
import ghidra.framework.Application;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.mem.MemoryBlock;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

public class ExportProgramMetadata extends GhidraScript {
    private static String hex(Address address) {
        return String.format("0x%08x", address.getUnsignedOffset());
    }

    private static String quote(String value) {
        StringBuilder output = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '\\': output.append("\\\\"); break;
                case '"': output.append("\\\""); break;
                case '\b': output.append("\\b"); break;
                case '\f': output.append("\\f"); break;
                case '\n': output.append("\\n"); break;
                case '\r': output.append("\\r"); break;
                case '\t': output.append("\\t"); break;
                default:
                    if (character < 0x20) {
                        output.append(String.format("\\u%04x", (int) character));
                    }
                    else {
                        output.append(character);
                    }
            }
        }
        return output.append('"').toString();
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 6) {
            throw new IllegalArgumentException(
                "expected: output_directory target source_path source_sha256 image_base reset_handler"
            );
        }

        Path outputDirectory = Path.of(arguments[0]);
        String target = arguments[1];
        String sourcePath = arguments[2];
        String sourceSha256 = arguments[3];
        long imageBase = Long.decode(arguments[4]);
        long resetHandler = Long.decode(arguments[5]);
        if (imageBase < 0 || resetHandler < imageBase) {
            throw new IllegalArgumentException("invalid image base or reset handler");
        }
        if (!sourceSha256.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("invalid source SHA-256");
        }

        Address resetAddress = currentProgram.getAddressFactory()
            .getDefaultAddressSpace().getAddress(resetHandler);
        if (currentProgram.getFunctionManager().getFunctionAt(resetAddress) == null) {
            if (!disassemble(resetAddress)) {
                throw new IllegalStateException("unable to disassemble reset handler");
            }
            createFunction(resetAddress, "reset_handler");
        }
        currentProgram.getSymbolTable().addExternalEntryPoint(resetAddress);

        List<MemoryBlock> blocks = new ArrayList<>(
            Arrays.asList(currentProgram.getMemory().getBlocks())
        );
        blocks.sort(Comparator.comparingLong(block -> block.getStart().getUnsignedOffset()));

        List<Address> entryPoints = new ArrayList<>();
        AddressIterator iterator = currentProgram.getSymbolTable().getExternalEntryPointIterator();
        while (iterator.hasNext()) {
            entryPoints.add(iterator.next());
        }
        entryPoints.sort(Comparator.comparingLong(Address::getUnsignedOffset));

        Files.createDirectories(outputDirectory);
        Path output = outputDirectory.resolve("program.json");
        try (BufferedWriter writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8)) {
            writer.write("{\n");
            writer.write("  \"schema_version\": 1,\n");
            writer.write("  \"target\": " + quote(target) + ",\n");
            writer.write("  \"tool\": {\"name\": \"Ghidra\", \"version\": "
                + quote(Application.getApplicationVersion()) + "},\n");
            writer.write("  \"source\": {\"path\": " + quote(sourcePath)
                + ", \"sha256\": " + quote(sourceSha256) + "},\n");
            writer.write("  \"architecture\": {\"language\": "
                + quote(currentProgram.getLanguageID().getIdAsString())
                + ", \"processor\": "
                + quote(currentProgram.getLanguage().getProcessor().toString())
                + ", \"endian\": "
                + quote(currentProgram.getLanguage().isBigEndian() ? "big" : "little")
                + "},\n");
            writer.write("  \"memory_blocks\": [\n");
            for (int index = 0; index < blocks.size(); index++) {
                MemoryBlock block = blocks.get(index);
                writer.write("    {\"name\": " + quote(block.getName())
                    + ", \"start\": " + quote(hex(block.getStart()))
                    + ", \"end\": " + quote(hex(block.getEnd()))
                    + ", \"initialized\": " + block.isInitialized() + "}");
                writer.write(index + 1 < blocks.size() ? ",\n" : "\n");
            }
            writer.write("  ],\n");
            writer.write("  \"entry_points\": [");
            for (int index = 0; index < entryPoints.size(); index++) {
                if (index > 0) writer.write(", ");
                writer.write(quote(hex(entryPoints.get(index))));
            }
            writer.write("]\n}\n");
        }
    }
}
