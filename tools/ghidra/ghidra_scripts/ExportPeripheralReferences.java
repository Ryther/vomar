// Export candidate references to selected nRF52840 peripheral ranges.
// @category Vimar30805

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ExportPeripheralReferences extends GhidraScript {
    private record Range(String name, long start, long end) {}
    private record Row(
        Address function, Address instruction, String peripheral, long offset,
        String access, String evidence
    ) {}

    private static final Pattern RANGE_PATTERN = Pattern.compile(
        "\\{\\s*\"name\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*"
        + "\"start\"\\s*:\\s*\"(0x[0-9a-fA-F]+)\"\\s*,\\s*"
        + "\"end\"\\s*:\\s*\"(0x[0-9a-fA-F]+)\"\\s*\\}"
    );

    private static String hex(Address address) {
        return String.format("0x%08x", address.getUnsignedOffset());
    }

    private static Range findRange(List<Range> ranges, long value) {
        for (Range range : ranges) {
            if (value >= range.start() && value < range.end()) return range;
        }
        return null;
    }

    private static String access(RefType type) {
        if (type.isWrite()) return "write";
        if (type.isRead()) return "read";
        if (type.isFlow()) return "execute";
        return "unknown";
    }

    private static List<Range> readRanges(Path path) throws Exception {
        String json = Files.readString(path, StandardCharsets.UTF_8);
        Matcher matcher = RANGE_PATTERN.matcher(json);
        List<Range> ranges = new ArrayList<>();
        while (matcher.find()) {
            ranges.add(new Range(
                matcher.group(1), Long.decode(matcher.group(2)), Long.decode(matcher.group(3))
            ));
        }
        if (ranges.isEmpty()) throw new IllegalArgumentException("no peripheral ranges found");
        ranges.sort(Comparator.comparingLong(Range::start));
        long previousEnd = 0;
        for (Range range : ranges) {
            if (range.start() < previousEnd || range.end() <= range.start()) {
                throw new IllegalArgumentException("overlapping or invalid peripheral range");
            }
            previousEnd = range.end();
        }
        return ranges;
    }

    private static void addRow(List<Row> rows, Set<String> seen, Row row) {
        String key = (row.function() == null ? "" : hex(row.function())) + ":"
            + hex(row.instruction()) + ":" + row.peripheral() + ":" + row.offset()
            + ":" + row.access() + ":" + row.evidence();
        if (seen.add(key)) rows.add(row);
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 2) {
            throw new IllegalArgumentException("expected: output_directory peripheral_config");
        }
        Path outputDirectory = Path.of(arguments[0]);
        List<Range> ranges = readRanges(Path.of(arguments[1]));
        Files.createDirectories(outputDirectory);

        List<Row> rows = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Instruction instruction : currentProgram.getListing().getInstructions(true)) {
            Function function = currentProgram.getFunctionManager()
                .getFunctionContaining(instruction.getAddress());
            Address functionAddress = function == null ? null : function.getEntryPoint();

            for (Reference reference : instruction.getReferencesFrom()) {
                long value = reference.getToAddress().getUnsignedOffset();
                Range range = findRange(ranges, value);
                if (range != null) {
                    addRow(rows, seen, new Row(
                        functionAddress, instruction.getAddress(), range.name(),
                        value - range.start(), access(reference.getReferenceType()),
                        "memory_reference"
                    ));
                }
            }
            for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                for (Object object : instruction.getOpObjects(operand)) {
                    if (!(object instanceof Scalar scalar)) continue;
                    long value = scalar.getUnsignedValue() & 0xffffffffL;
                    Range range = findRange(ranges, value);
                    if (range != null) {
                        addRow(rows, seen, new Row(
                            functionAddress, instruction.getAddress(), range.name(),
                            value - range.start(), "unknown", "scalar_constant"
                        ));
                    }
                }
            }
        }
        rows.sort(Comparator
            .comparingLong((Row row) -> row.instruction().getUnsignedOffset())
            .thenComparing(Row::peripheral)
            .thenComparingLong(Row::offset)
            .thenComparing(Row::evidence));

        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("peripheral_refs.tsv"), StandardCharsets.UTF_8)) {
            writer.write("function_address\tinstruction_address\tperipheral\toffset\taccess\tevidence\n");
            for (Row row : rows) {
                writer.write((row.function() == null ? "" : hex(row.function())) + "\t"
                    + hex(row.instruction()) + "\t" + row.peripheral() + "\t"
                    + String.format("0x%x", row.offset()) + "\t" + row.access() + "\t"
                    + row.evidence() + "\n");
            }
        }
    }
}
