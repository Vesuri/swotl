// Research only. Input: tools/tfh_xref.py's relocated BOB.bin at 0x10000.
//@category SWOTL
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class SeedTfh extends GhidraScript {
    public void run() throws Exception {
        disassemble(toAddr(0x10000));
        // Aztec LINK A5 prologues are analysis candidates, not proven entries.
        for (long at = 0x10000; at < 0x41e40; at += 2) {
            if ((getShort(toAddr(at)) & 65535) == 0x4e55) {
                disassemble(toAddr(at));
                if (getFunctionAt(toAddr(at)) == null) createFunction(toAddr(at), null);
            }
        }
        // A4-relative JMP absolute-long thunks into the code hunk.
        for (long at = 0x41e40; at < 0x42240; at += 2) {
            if ((getShort(toAddr(at)) & 65535) == 0x4ef9) {
                disassemble(toAddr(at));
                if (getFunctionAt(toAddr(at)) == null) createFunction(toAddr(at), null);
            }
        }
        long[] entries = {0x1139a, 0x1141a, 0x1146a, 0x118ec, 0x21138,
                          0x2142c, 0x37d40};
        String[] names = {"research_index_sprite_records", "research_copy_sprite_indices",
                          "research_load_delimited_records", "research_read_resource",
                          "research_visit_terrain_rings", "research_draw_ground_object",
                          "research_draw_packed_image"};
        for (int i = 0; i < entries.length; i++) {
            disassemble(toAddr(entries[i]));
            Function f = getFunctionAt(toAddr(entries[i]));
            if (f == null) f = createFunction(toAddr(entries[i]), names[i]);
            if (f == null) throw new IllegalStateException("missing function " + names[i]);
            f.setName(names[i], SourceType.USER_DEFINED);
        }
    }
}
