// Export stable structural fingerprints for cross-firmware matching.
// @category Vimar30805

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.block.BasicBlockModel;
import ghidra.program.model.block.CodeBlock;
import ghidra.program.model.block.CodeBlockIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ExportFunctionFingerprints extends GhidraScript {
    private static String hex(Address address) {
        return String.format("0x%08x", address.getUnsignedOffset());
    }

    private static String digestHex(MessageDigest digest) {
        StringBuilder output = new StringBuilder();
        for (byte value : digest.digest()) output.append(String.format("%02x", value & 0xff));
        return output.toString();
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected: output_directory");
        }
        Path outputDirectory = Path.of(arguments[0]);
        Files.createDirectories(outputDirectory);
        List<Function> functions = new ArrayList<>();
        currentProgram.getFunctionManager().getFunctions(true).forEachRemaining(functions::add);
        functions.sort(Comparator.comparingLong(
            function -> function.getEntryPoint().getUnsignedOffset()
        ));
        BasicBlockModel blockModel = new BasicBlockModel(currentProgram);

        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("function_fingerprints.tsv"), StandardCharsets.UTF_8)) {
            writer.write("address\tbyte_size\tinstruction_count\tbasic_blocks\tcyclomatic"
                + "\tcalls\tunique_constants\tmnemonic_sha256\texact_bytes_sha256\n");
            for (Function function : functions) {
                MessageDigest mnemonicDigest = MessageDigest.getInstance("SHA-256");
                MessageDigest byteDigest = MessageDigest.getInstance("SHA-256");
                int instructionCount = 0;
                int calls = 0;
                Set<Long> constants = new HashSet<>();
                for (Instruction instruction : currentProgram.getListing()
                        .getInstructions(function.getBody(), true)) {
                    instructionCount++;
                    mnemonicDigest.update(
                        instruction.getMnemonicString().toUpperCase().getBytes(StandardCharsets.US_ASCII)
                    );
                    mnemonicDigest.update((byte) 0);
                    for (Reference reference : instruction.getReferencesFrom()) {
                        if (reference.getReferenceType().isCall()) calls++;
                    }
                    for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                        for (Object object : instruction.getOpObjects(operand)) {
                            if (object instanceof Scalar scalar) {
                                constants.add(scalar.getUnsignedValue());
                            }
                        }
                    }
                }
                AddressIterator addresses = function.getBody().getAddresses(true);
                while (addresses.hasNext()) {
                    byteDigest.update(currentProgram.getMemory().getByte(addresses.next()));
                }

                int blocks = 0;
                int edges = 0;
                CodeBlockIterator blockIterator = blockModel.getCodeBlocksContaining(
                    function.getBody(), monitor
                );
                while (blockIterator.hasNext()) {
                    CodeBlock block = blockIterator.next();
                    blocks++;
                    edges += block.getNumDestinations(monitor);
                }
                int cyclomatic = Math.max(1, edges - blocks + 2);
                writer.write(hex(function.getEntryPoint()) + "\t"
                    + function.getBody().getNumAddresses() + "\t" + instructionCount + "\t"
                    + blocks + "\t" + cyclomatic + "\t" + calls + "\t"
                    + constants.size() + "\t" + digestHex(mnemonicDigest) + "\t"
                    + digestHex(byteDigest) + "\n");
            }
        }
    }
}
