// Export deterministic defined strings and references to them.
// @category Vimar30805

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.util.DefinedStringIterator;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ExportStrings extends GhidraScript {
    private record StringRow(Address address, String encoding, int length, String value) {}
    private record XrefRow(
        Address stringAddress, Address fromAddress, Address functionAddress, String refType
    ) {}

    private static String hex(Address address) {
        return String.format("0x%08x", address.getUnsignedOffset());
    }

    private static String escape(String value) {
        StringBuilder output = new StringBuilder();
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character == '\\') output.append("\\\\");
            else if (character == '\t') output.append("\\t");
            else if (character == '\r') output.append("\\r");
            else if (character == '\n') output.append("\\n");
            else if (character < 0x20 || character == 0x7f) {
                output.append(String.format("\\x%02x", (int) character));
            }
            else output.append(character);
        }
        return output.toString();
    }

    private static String cleanField(String value) {
        return escape(value == null ? "" : value);
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected: output_directory");
        }
        Path outputDirectory = Path.of(arguments[0]);
        Files.createDirectories(outputDirectory);

        List<StringRow> strings = new ArrayList<>();
        List<XrefRow> xrefs = new ArrayList<>();
        Set<String> seenXrefs = new HashSet<>();
        for (Data data : DefinedStringIterator.forProgram(currentProgram)) {
            StringDataInstance instance = StringDataInstance.getStringDataInstance(data);
            String value = instance.getStringValue();
            if (value == null) continue;
            Address stringAddress = data.getAddress();
            strings.add(new StringRow(
                stringAddress,
                cleanField(instance.getCharsetName()),
                data.getLength(),
                escape(value)
            ));

            ReferenceIterator references = currentProgram.getReferenceManager()
                .getReferencesTo(stringAddress);
            while (references.hasNext()) {
                Reference reference = references.next();
                Address fromAddress = reference.getFromAddress();
                Function function = currentProgram.getFunctionManager()
                    .getFunctionContaining(fromAddress);
                Address functionAddress = function == null ? null : function.getEntryPoint();
                String refType = cleanField(reference.getReferenceType().getName());
                String key = hex(stringAddress) + ":" + hex(fromAddress) + ":"
                    + (functionAddress == null ? "" : hex(functionAddress)) + ":" + refType;
                if (seenXrefs.add(key)) {
                    xrefs.add(new XrefRow(
                        stringAddress, fromAddress, functionAddress, refType
                    ));
                }
            }
        }

        strings.sort(Comparator.comparingLong(row -> row.address().getUnsignedOffset()));
        xrefs.sort(Comparator
            .comparingLong((XrefRow row) -> row.stringAddress().getUnsignedOffset())
            .thenComparingLong(row -> row.fromAddress().getUnsignedOffset())
            .thenComparing(row -> row.functionAddress() == null ? "" : hex(row.functionAddress()))
            .thenComparing(XrefRow::refType));

        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("strings.tsv"), StandardCharsets.UTF_8)) {
            writer.write("address\tencoding\tlength\tvalue\n");
            for (StringRow row : strings) {
                writer.write(hex(row.address()) + "\t" + row.encoding() + "\t"
                    + row.length() + "\t" + row.value() + "\n");
            }
        }
        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("string_xrefs.tsv"), StandardCharsets.UTF_8)) {
            writer.write("string_address\tfrom_address\tfunction_address\tref_type\n");
            for (XrefRow row : xrefs) {
                writer.write(hex(row.stringAddress()) + "\t" + hex(row.fromAddress()) + "\t"
                    + (row.functionAddress() == null ? "" : hex(row.functionAddress())) + "\t"
                    + row.refType() + "\n");
            }
        }
    }
}
