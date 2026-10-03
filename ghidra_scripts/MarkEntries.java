// Seed traced and static entries from a CSV (arg0): link linear hex, kind, name.
// kind "code" = disassemble (traced instruction start); "func" = entry + function.
//@category SWOTL
import java.io.BufferedReader;
import java.io.FileReader;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class MarkEntries extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("MarkEntries needs an entry CSV");
        int code = 0, functions = 0;
        try (BufferedReader reader = new BufferedReader(new FileReader(args[0]))) {
            String line;
            while ((line = reader.readLine()) != null) {
                monitor.checkCancelled();
                line = line.trim();
                if (line.isEmpty() || line.startsWith("linear,")) continue;
                String[] f = line.split(",", 3);
                Address address = toAddr(Long.parseLong(f[0].replaceFirst("^0x", ""), 16));
                disassemble(address);
                if (f[1].equals("func")) {
                    addEntryPoint(address);
                    Function function = getFunctionAt(address);
                    if (function == null) createFunction(address, f[2]);
                    else if (function.getSymbol().getSource() != SourceType.USER_DEFINED)
                        function.setName(f[2], SourceType.USER_DEFINED);
                    functions++;
                } else {
                    code++;
                }
            }
        }
        println("MarkEntries: " + code + " traced starts, " + functions + " functions");
    }
}
