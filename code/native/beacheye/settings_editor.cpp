#include "settings_editor.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <string>
#include <type_traits>

namespace {
class Fields {
    cJSON* output;
    const cJSON* input;
public:
    bool valid = true;
    Fields(cJSON* out, const cJSON* in) : output(out), input(in) {}

    // Dotted internal UI paths keep the existing Qt bindings. They are not
    // the company's JSON file format and never invoke its validating exporter.
    cJSON* node(const std::string& path) {
        cJSON* parent = output ? output : const_cast<cJSON*>(input);
        size_t begin = 0;
        while (parent) {
            const auto end = path.find('.', begin);
            const auto key = path.substr(begin, end - begin);
            const bool index = key[0] >= '0' && key[0] <= '9';
            auto* next = index ? cJSON_GetArrayItem(parent, std::stoi(key))
                               : cJSON_GetObjectItemCaseSensitive(parent, key.c_str());
            if (!next && output) {
                const bool leaf = end == std::string::npos;
                const bool array = !leaf && path[end + 1] >= '0' && path[end + 1] <= '9';
                next = leaf ? cJSON_CreateNull() : array ? cJSON_CreateArray() : cJSON_CreateObject();
                if (index) cJSON_AddItemToArray(parent, next);
                else cJSON_AddItemToObject(parent, key.c_str(), next);
            }
            if (end == std::string::npos) return next;
            parent = next;
            begin = end + 1;
        }
        return nullptr;
    }

    template<class T> void field(const std::string& path, T& value) {
        auto* item = node(path);
        if (output) {
            item->type = cJSON_Number;
            cJSON_SetNumberValue(item, static_cast<double>(value));
        } else if (item) {
            const double number = item->valuedouble;
            using Storage = decltype(storage_type<T>());
            if (!cJSON_IsNumber(item) || !std::isfinite(number) ||
                number < std::numeric_limits<Storage>::lowest() ||
                number > std::numeric_limits<Storage>::max() ||
                (std::is_integral_v<Storage> && std::trunc(number) != number)) {
                valid = false;
                return;
            }
            value = static_cast<T>(number);
        }
    }
    template<class T> static auto storage_type() {
        if constexpr (std::is_enum_v<T>) return std::underlying_type_t<T>{};
        else return T{};
    }
    template<size_t N> void text(const std::string& path, char (&value)[N]) {
        auto* item = node(path);
        if (output) {
            item->type = cJSON_String;
            const std::string bounded(value, std::find(value, value + N, '\0'));
            item->valuestring = static_cast<char*>(cJSON_malloc(bounded.size() + 1));
            std::memcpy(item->valuestring, bounded.c_str(), bounded.size() + 1);
        } else if (item) {
            if (!cJSON_IsString(item) || std::strlen(item->valuestring) >= N) valid = false;
            else {
                std::memset(value, 0, N);
                std::memcpy(value, item->valuestring, std::strlen(item->valuestring));
            }
        }
    }
};

void element(Fields& f, const std::string& p, Element& e, int kind) {
    f.field(p + ".e", e.enabled);
    for (int i = 0; i < 4; ++i) f.field(p + ".a." + std::to_string(i), e.ar_mode[i]);
    const auto t = kind == 0 ? p + ".t" : p;
    f.field(t + ".i", e.tcc.Ip);
    f.field(t + ".tt", e.tcc.Tt);
    if (kind == 2) f.field(t + ".tr", e.tcc.Tres);
    if (kind != 0) return;
    f.field(t + ".t", e.tcc.type);
    f.field(t + ".tm", e.tcc.TM);
    f.field(t + ".mi", e.tcc.MIN);
    f.field(t + ".tmi", e.tcc.Tmin);
    f.field(t + ".tma", e.tcc.Tmax);
    f.field(t + ".ta", e.tcc.Ta);
    f.field(t + ".tr", e.tcc.Tres);
    f.field(t + ".mm", e.tcc.max_mode);
}

void ocef(Fields& f, const std::string& p, OCEF_Pack& e) {
    f.field(p + ".at", e.At);
    ElementPack* directions[] = {&e.forward, &e.reverse};
    for (int i = 0; i < 2; ++i) {
        const auto d = p + (i == 0 ? ".f" : ".r");
        element(f, d + ".d", directions[i]->delayed, 0);
        element(f, d + ".f", directions[i]->fast_trip, 0);
        element(f, d + ".h", directions[i]->high_set, 1);
    }
}
template<class T> void voltage(Fields& f, const std::string& p, T& v) {
    f.field(p + ".u", v.um);
    f.field(p + ".t", v.Tt);
    f.field(p + ".a", v.ar_mode);
}

void visit(Fields& f, Configure& c) {
#define F(path, member) f.field(path, member)
#define A(path, member, count) for (int j = 0; j < count; ++j) F(std::string(path) + "." + std::to_string(j), member[j])
    F("sy.l.b", c.system.lcd.backlight);
    F("sy.m.ss", c.system.me.source);
    F("sy.m.pc", c.system.me.phase_config);
    F("sy.m.f", c.system.me.frequency);
    F("sy.m.v", c.system.me.voltage);
    F("sy.m.lsd", c.lsd_level);
    A("sy.m.ca", c.system.me.calib, 6);
    F("sy.io.r.0", c.system.io.digital_read_mode.open);
    F("sy.io.r.1", c.system.io.digital_read_mode.close);
    F("sy.io.i.v", c.io_input.valid_time);
    F("sy.io.i.c", c.chatter.enabled);
    F("sy.io.i.r", c.chatter.reset);
    F("sy.io.e.d", c.scada.ports.eth.dhcp);
    F("sy.io.m.p", c.modem.mode);
    F("sy.io.m.b", c.modem.baudrate);
    f.text("sy.io.m.a", c.apn);
    F("s.d", c.scada.dataport);
    F("s.p", c.scada.protocol);
    F("s.s", c.scada_status);
    F("s.dn.l.a.0", c.scada.dnp3.link.slave_addr);
    F("s.dn.l.a.1", c.scada.dnp3.link.master_addr);
    F("s.dn.l.ct", c.scada.dnp3.link.confirm_timeout);
    F("s.dn.l.k", c.scada.dnp3.link.keep_alive);
    F("s.dn.l.cr", c.scada.dnp3.link.confirm_retry);
    F("s.dn.l.cu", c.scada.dnp3.link.confirm_user_data);
    F("s.dn.l.ke", c.scada.dnp3.link.keep_alive_enable);
    F("s.dn.a.c", c.scada.dnp3.app.cold_restart_delay);
    F("s.dn.a.w", c.scada.dnp3.app.warm_restar_dealy);
    F("s.dn.a.sc", c.scada.dnp3.app.solicited_confirm_timeout);
    F("s.dn.a.st", c.scada.dnp3.app.select_timeout);
    F("s.dn.u.e", c.scada.dnp3.unsoli.enabled);
    F("s.dn.u.h", c.scada.dnp3.unsoli.hold_time);
    F("s.dn.t.e", c.scada.dnp3.timesync.enabled);
    F("s.dn.t.r", c.scada.dnp3.timesync.request_time);
    F("se.as", c.sec.tls);
    A("se.p", c.pass, 4);
    F("p.le", c.ll_en);
    F("p.a", c.prot.active_group);
    F("p.fl.e", c.fl.enabled);
    F("p.ol.n", c.overload.min_IN);
    F("p.ol.z", c.overload.min_IZ);
    Configure::Overload::OLElement* overloads[] = {&c.overload.sym, &c.overload.asym};
    for (int i = 0; i < 2; ++i) {
        const std::string p = i ? "p.ol.a" : "p.ol.s";
        F(p + ".m", overloads[i]->mode); F(p + ".i", overloads[i]->Ip);
        F(p + ".t", overloads[i]->Tt); F(p + ".r", overloads[i]->Tres);
    }
    F("p.sy.c.t", c.sync.sync_check.time);
    F("p.sy.a.t", c.sync.auto_sync.wait_time);
    F("uf", c.uf_on); F("uv", c.uv_on); F("pi", c.prot_inrush);
    F("onc", c.open_need_confirm); F("cnc", c.close_need_confirm);
    F("cd", c.cert_default); F("sen", c.sectionalizer_en);
    F("sy.h.s", c.heater.status); F("sy.h.on", c.heater.on_temp); F("sy.h.of", c.heater.off_temp);

    // Named scalar bindings are expanded below; every assignment targets the
    // compiler's actual field, independent of Configure padding and layout.
    F("sy.m.c.0", c.system.me.coef.ia);
    F("sy.m.c.1", c.system.me.coef.ib);
    F("sy.m.c.2", c.system.me.coef.ic);
    F("sy.m.c.3", c.system.me.coef.in);
    F("sy.m.db.0", c.system.me.deadbands.voltage);
    F("sy.m.db.1", c.system.me.deadbands.bt_voltage);
    F("sy.m.db.2", c.system.me.deadbands.current);
    F("sy.m.db.3", c.system.me.deadbands.g_current);
    F("sy.m.db.4", c.system.me.deadbands.pf);
    F("sy.m.db.5", c.system.me.deadbands.frequency);
    F("sy.m.db.6", c.system.me.deadbands.power);
    F("sy.m.db.7", c.system.me.deadbands.counter);
    F("sy.io.i.g.0", c.system.io.inputs.input1);
    F("sy.io.i.g.1", c.system.io.inputs.input2);
    F("sy.io.i.g.2", c.system.io.inputs.input3);
    F("sy.io.i.g.3", c.system.io.inputs.input4);
    F("sy.io.i.g.4", c.system.io.inputs.input5);
    F("sy.io.i.g.5", c.system.io.inputs.input6);
    F("sy.io.i.g.6", c.system.io.inputs.input7);
    F("s.dn.u.u.0", c.unsoli.clazz0);
    F("s.dn.u.u.1", c.unsoli.clazz1);
    F("s.dn.u.u.2", c.unsoli.clazz2);
    F("s.dn.u.u.3", c.unsoli.clazz3);
    F("s.ma.0", c.scada.dnp3.mapping.s_bin);
    F("s.ma.1", c.scada.dnp3.mapping.e_bin);
    F("s.ma.2", c.scada.dnp3.mapping.s_ana);
    F("s.ma.3", c.scada.dnp3.mapping.e_ana);
    F("s.ma.4", c.scada.dnp3.mapping.s_dbl);
    F("s.ma.5", c.scada.dnp3.mapping.e_dbl);
    F("s.ma.6", c.scada.dnp3.mapping.s_bot);
    F("s.ma.7", c.scada.dnp3.mapping.e_bot);
    F("s.ma.8", c.scada.dnp3.mapping.s_aot);
    F("s.ma.9", c.scada.dnp3.mapping.e_aot);
    F("s.ma.10", c.scada.dnp3.mapping.s_cnt);
    F("s.ma.11", c.scada.dnp3.mapping.e_cnt);
    F("s.ma.12", c.scada.dnp3.mapping.s_str);
    F("p.p.0", c.prot.prot_en);
    F("p.p.1", c.prot.sef_en);
    F("p.p.2", c.prot.oc_en);
    F("p.p.3", c.prot.ef_en);
    F("p.p.4", c.prot.clp_en);
    F("p.s.0", c.ol_en);
    F("p.s.1", c.harmonic_en);
    F("p.s.2", c.nps_en);
    F("p.s.3", c.admittance_en);
    F("p.s.4", c.abr_on);
    F("p.s.5", c.alarm_mode_on);
    F("p.s.6", c.uv4_sag_on);
    F("p.s.7", c.ov_on);
    F("p.s.8", c.ov3_on);
    F("p.s.9", c.of_on);
    F("p.s.10", c.rocof_on);
    F("p.s.11", c.vvs_on);
    F("p.s.12", c.hot_line_tag_on);
    F("p.s.13", c.ll_link_to_hlt_on);
    F("p.s.14", c.ssm_on);
    F("p.s.15", c.dft_on);
    F("p.s.16", c.mnt_on);
    F("p.s.17", c.llb_on);
    F("p.s.18", c.hib_on);
    F("p.s.19", c.pdop_on);
    F("p.s.20", c.pdup_on);
    F("p.s.21", c.logical_block_close);
    F("p.s.22", c.breaker_en);
    F("p.s.23", c.external);
    F("p.fl.v.0", c.fl.r0);
    F("p.fl.v.1", c.fl.x0);
    F("p.fl.v.2", c.fl.r1);
    F("p.fl.v.3", c.fl.x1);
    F("p.fl.v.4", c.fl.l);
    F("p.sy.g.0", c.sync.mode);
    F("p.sy.g.1", c.sync.phase_selection);
    F("p.sy.g.2", c.sync.bus_line);
    F("p.sy.g.3", c.sync.dldb_auto_reclose);
    F("p.sy.g.4", c.sync.dldb_manual_close);
    F("p.sy.g.5", c.sync.live_dead_auto_reclose);
    F("p.sy.g.6", c.sync.live_dead_manual_close);
    F("p.sy.g.7", c.sync.live_bus_vm);
    F("p.sy.g.8", c.sync.live_line_vm);
    F("p.sy.g.9", c.sync.bus_max_v);
    F("p.sy.g.10", c.sync.line_max_v);
    F("p.sy.g.11", c.sync.voltage_diff);
    F("p.sy.c.s.0", c.sync.sync_check.mode);
    F("p.sy.c.s.1", c.sync.sync_check.frequecny);
    F("p.sy.c.s.2", c.sync.sync_check.angel);
    F("p.sy.a.s.0", c.sync.auto_sync.freq_rated);
    F("p.sy.a.s.1", c.sync.auto_sync.max_freq_dev);
    F("p.sy.a.s.2", c.sync.auto_sync.max_freq_slip);
    F("p.sy.a.s.3", c.sync.auto_sync.max_freq_change_rate);
    F("p.sy.a.s.4", c.sync.auto_sync.anti_motoring);
    F("sy.io.r2.0", c.scada.ports.rs232.baudrate);
    F("sy.io.r2.1", c.scada.ports.rs232.parity);
    F("sy.io.r2.2", c.scada.ports.rs232.stopbits);
    F("sy.io.r2.3", c.scada.ports.rs232.databits);
    F("sy.io.r4.0", c.scada.ports.rs485.baudrate);
    F("sy.io.r4.1", c.scada.ports.rs485.parity);
    F("sy.io.r4.2", c.scada.ports.rs485.stopbits);
    F("sy.io.r4.3", c.scada.ports.rs485.databits);
    F("sy.io.e.i.0", c.scada.ports.eth.ip.octet_1);
    F("sy.io.e.i.1", c.scada.ports.eth.ip.octet_2);
    F("sy.io.e.i.2", c.scada.ports.eth.ip.octet_3);
    F("sy.io.e.i.3", c.scada.ports.eth.ip.octet_4);
    F("sy.io.e.s.0", c.scada.ports.eth.subnetmask.octet_1);
    F("sy.io.e.s.1", c.scada.ports.eth.subnetmask.octet_2);
    F("sy.io.e.s.2", c.scada.ports.eth.subnetmask.octet_3);
    F("sy.io.e.s.3", c.scada.ports.eth.subnetmask.octet_4);
    F("sy.io.e.g.0", c.scada.ports.eth.gateway.octet_1);
    F("sy.io.e.g.1", c.scada.ports.eth.gateway.octet_2);
    F("sy.io.e.g.2", c.scada.ports.eth.gateway.octet_3);
    F("sy.io.e.g.3", c.scada.ports.eth.gateway.octet_4);
    F("s.dn.e.i.0", c.scada.dnp3.tcp.remote_ip.octet_1);
    F("s.dn.e.i.1", c.scada.dnp3.tcp.remote_ip.octet_2);
    F("s.dn.e.i.2", c.scada.dnp3.tcp.remote_ip.octet_3);
    F("s.dn.e.i.3", c.scada.dnp3.tcp.remote_ip.octet_4);
    F("s.dn.m.i.0", c.scada.iec.iec104.tcp.remote_ip.octet_1);
    F("s.dn.m.i.1", c.scada.iec.iec104.tcp.remote_ip.octet_2);
    F("s.dn.m.i.2", c.scada.iec.iec104.tcp.remote_ip.octet_3);
    F("s.dn.m.i.3", c.scada.iec.iec104.tcp.remote_ip.octet_4);
    F("s.dn.e.m", c.scada.dnp3.tcp.mode);
    F("s.dn.e.l", c.scada.dnp3.tcp.local_port);
    F("s.dn.e.r", c.scada.dnp3.tcp.remote_port);
    F("s.dn.m.m", c.scada.iec.iec104.tcp.mode);
    F("s.dn.m.l", c.scada.iec.iec104.tcp.local_port);
    F("s.dn.m.r", c.scada.iec.iec104.tcp.remote_port);

    for (int i = 0; i < 16; ++i) {
        const auto p = "sy.fn." + std::to_string(i);
        auto& fn = c.funcs[i];
        F(p + ".t", fn.time); F(p + ".v", fn.avalue);
        A(p + ".o", fn.doperands, 3); F(p + ".o.3", fn.aoperand);
        F(p + ".s.0", fn.enabled); F(p + ".s.1", fn.dvalue);
        F(p + ".s.2", fn.source); F(p + ".s.3", fn.doperator);
        F(p + ".s.4", fn.aoperator); F(p + ".s.5", fn.action);
    }
    Configure::System::IO::Outputs::Output* outputs[] = {
        &c.system.io.outputs.output1, &c.system.io.outputs.output2,
        &c.system.io.outputs.output3, &c.system.io.outputs.output4,
        &c.system.io.outputs.output5, &c.system.io.outputs.output6,
        &c.system.io.outputs.output7, &c.system.io.outputs.output8,
    };
    for (int i = 0; i < 8; ++i) {
        const auto p = "sy.io.o." + std::to_string(i);
        F(p + ".i", outputs[i]->index); F(p + ".a", outputs[i]->active_at);
        F(p + ".s", outputs[i]->status); F(p + ".o", outputs[i]->on_time);
        F(p + ".t", c.do_time[i]);
    }
    for (int i = 0; i < 4; ++i) {
        const auto p = "p.g." + std::to_string(i);
        auto& g = c.prot.groups[i]; auto& ex = c.p_e[i];
        ocef(f, p + ".o", g.ocef.oc); ocef(f, p + ".e", g.ocef.ef);
        ocef(f, p + ".nps", c.nps[i]);
        element(f, p + ".sf.f", g.sef.sef.forward, 2);
        element(f, p + ".sf.r", g.sef.sef.reverse, 2);
        F(p + ".sf.at", g.sef.At);
        F(p + ".c.c", g.ocef.clp.CLM); F(p + ".c.t", g.ocef.clp.Tcl); F(p + ".c.r", g.ocef.clp.Trec);
        F(p + ".i.i", g.ocef.ir.IRM); F(p + ".i.t", g.ocef.ir.Tir);
        F(p + ".sc.s", g.sectionalizing_mode); F(p + ".sc.t", g.sectionalizing_trip_need);
        F(p + ".sc.r", g.sectionalizing_reset_time);
        F(p + ".r.e", ex.recloser_en);
        A(p + ".r.oe.t", ex.oc.ocef.Tr, 3); F(p + ".r.oe.t.3", ex.oc.ocef.Tres);
        F(p + ".r.oe.le", ex.oc.lsrm.enabled); F(p + ".r.oe.lt", ex.oc.lsrm.time);
        F(p + ".r.oe.v", ex.oc.vrc_control);
        F(p + ".ll.o.i", c.ll[i].oc.tcc.Ip); F(p + ".ll.o.tt", c.ll[i].oc.tcc.Tt);
        F(p + ".ll.e.i", c.ll[i].ef.tcc.Ip); F(p + ".ll.e.tt", c.ll[i].ef.tcc.Tt);
        F(p + ".bc.m", c.bc[i].mode); F(p + ".bc.p", c.bc[i].pickup);
        F(p + ".bc.t", c.bc[i].Tt); F(p + ".bc.n", c.bc[i].min_IN);
        F(p + ".sst.e", c.sst[i].enabled); F(p + ".sst.t", c.sst[i].time);
        F(p + ".r.v.0", c.vrc[i].mode); F(p + ".r.v.1", c.vrc[i].vm);
        F(p + ".r.l.0", c.llb[i].mode); F(p + ".r.l.1", c.llb[i].vm);
        F(p + ".uv.c", ex.uv.auto_close); F(p + ".uv.r", ex.ov.reclose_time);
        F(p + ".uv.f.0", ex.uv.auto_close_en); F(p + ".uv.f.1", ex.uv.sst_only); F(p + ".uv.f.2", ex.uv.num_of_trip);
        voltage(f, p + ".uv.u.0", ex.uv.uv1); voltage(f, p + ".uv.u.1", ex.uv.uv2); voltage(f, p + ".uv.u.2", ex.uv.uv3);
        voltage(f, p + ".uv.u.3", c.ve[i].uv12); voltage(f, p + ".uv.u.4", c.ve[i].uv13);
        voltage(f, p + ".uv.u.5", c.ve[i].uv22); voltage(f, p + ".uv.u.6", c.ve[i].uv23);
        voltage(f, p + ".ov.0", ex.ov.ov1); voltage(f, p + ".ov.1", c.ov2_4[i].ov2);
        voltage(f, p + ".ov.2", c.ov3[i]); voltage(f, p + ".ov.3", c.ov2_4[i].ov4);
        voltage(f, p + ".ov.4", c.ve[i].ov12); voltage(f, p + ".ov.5", c.ve[i].ov13);
        voltage(f, p + ".ov.6", c.ve[i].ov22); voltage(f, p + ".ov.7", c.ve[i].ov23);
        F(p + ".ov.2.mam", c.ov3[i].moving_average_mode); F(p + ".ov.2.maw", c.ov3[i].moving_average_window);
        F(p + ".f.u.m", ex.uf.mode); F(p + ".f.u.p", ex.uf.fp); F(p + ".f.u.t", ex.uf.Tt);
        F(p + ".f.o.m", c.of[i].mode); F(p + ".f.o.p", c.of[i].fp); F(p + ".f.o.t", c.of[i].Tt);
        auto& a = ex.abr;
        F(p + ".a.e", a.enabled); F(p + ".a.a", a.auto_open_mode); F(p + ".a.d", a.open_power_flow.dir_changed);
        F(p + ".a.r", a.open_power_flow.reduced); F(p + ".a.rt", a.restoration_time);
        F(p + ".a.ot", a.open_timer.T_ao); F(p + ".a.oo", a.open_timer.operations);
        F(p + ".a.or", a.open_power_flow.reduced_percent); F(p + ".a.op", a.open_power_flow.T_ao);
        auto& ad = c.admittance[i];
        A(p + ".ad.a", ad.ar_mode, 4); F(p + ".ad.a.4", ad.mode); F(p + ".ad.a.5", ad.dir_mode); F(p + ".ad.a.6", ad.min_Vn_mult);
        F(p + ".ad.b.0", ad.Tt); F(p + ".ad.b.1", ad.Tr);
        F(p + ".ad.c.0", ad.min_In); F(p + ".ad.c.1", ad.forward_susceptance); F(p + ".ad.c.2", ad.reverse_susceptance);
        F(p + ".ad.c.3", ad.forward_conductance); F(p + ".ad.c.4", ad.reverse_conductance);
        F(p + ".cm.0", c.c_max[i].oc2_f);
        F(p + ".cm.1", c.c_max[i].oc2_r);
        F(p + ".cm.2", c.c_max[i].ef2_f);
        F(p + ".cm.3", c.c_max[i].ef2_r);
        F(p + ".cm.4", c.c_max[i].nps2_f);
        F(p + ".cm.5", c.c_max[i].nps2_r);
        F(p + ".i.h.0.0", c.hrm_blocking[i]._2nd.mode);
        F(p + ".i.h.0.1", c.hrm_blocking[i]._2nd.level);
        F(p + ".i.h.0.2", c.hrm_blocking[i]._2nd.time);
        F(p + ".i.h.1.0", c.hrm_blocking[i]._5th.mode);
        F(p + ".i.h.1.1", c.hrm_blocking[i]._5th.level);
        F(p + ".i.h.1.2", c.hrm_blocking[i]._5th.time);
        F(p + ".d.0.0", c.dir[i].oc.not_detected);
        F(p + ".d.0.1", c.dir[i].oc.change);
        F(p + ".d.0.2", c.dir[i].oc._1_F);
        F(p + ".d.0.3", c.dir[i].oc._2_F);
        F(p + ".d.0.4", c.dir[i].oc._3_F);
        F(p + ".d.0.5", c.dir[i].oc._1_R);
        F(p + ".d.0.6", c.dir[i].oc._2_R);
        F(p + ".d.0.7", c.dir[i].oc._3_R);
        F(p + ".d.1.0", c.dir[i].ef.not_detected);
        F(p + ".d.1.1", c.dir[i].ef.change);
        F(p + ".d.1.2", c.dir[i].ef._1_F);
        F(p + ".d.1.3", c.dir[i].ef._2_F);
        F(p + ".d.1.4", c.dir[i].ef._3_F);
        F(p + ".d.1.5", c.dir[i].ef._1_R);
        F(p + ".d.1.6", c.dir[i].ef._2_R);
        F(p + ".d.1.7", c.dir[i].ef._3_R);
        F(p + ".d.2.0", c.dir[i].nps.not_detected);
        F(p + ".d.2.1", c.dir[i].nps.change);
        F(p + ".d.2.2", c.dir[i].nps._1_F);
        F(p + ".d.2.3", c.dir[i].nps._2_F);
        F(p + ".d.2.4", c.dir[i].nps._3_F);
        F(p + ".d.2.5", c.dir[i].nps._1_R);
        F(p + ".d.2.6", c.dir[i].nps._2_R);
        F(p + ".d.2.7", c.dir[i].nps._3_R);
        F(p + ".d.3.0", c.dir[i].sef.not_detected);
        F(p + ".d.3.1", c.dir[i].sef.change);
        F(p + ".d.3.2", c.dir[i].sef.forward);
        F(p + ".d.3.3", c.dir[i].sef.reverse);
        F(p + ".h.t.h.m", c.harmonic[i].thd.mode);
        F(p + ".h.t.h.l", c.harmonic[i].thd.level);
        F(p + ".h.t.h.t", c.harmonic[i].thd.Tt);
        F(p + ".h.t.d.m", c.harmonic[i].tdd.mode);
        F(p + ".h.t.d.l", c.harmonic[i].tdd.level);
        F(p + ".h.t.d.t", c.harmonic[i].tdd.Tt);
        F(p + ".h.i.m", c.harmonic[i].ind.mode);
        F(p + ".h.i.t", c.harmonic[i].ind.Tt);
        F(p + ".h.i.s.0.m", c.harmonic[i].ind.a.mode);
        F(p + ".h.i.s.0.l", c.harmonic[i].ind.a.level);
        F(p + ".h.i.s.1.m", c.harmonic[i].ind.b.mode);
        F(p + ".h.i.s.1.l", c.harmonic[i].ind.b.level);
        F(p + ".h.i.s.2.m", c.harmonic[i].ind.c.mode);
        F(p + ".h.i.s.2.l", c.harmonic[i].ind.c.level);
        F(p + ".h.i.s.3.m", c.harmonic[i].ind.d.mode);
        F(p + ".h.i.s.3.l", c.harmonic[i].ind.d.level);
        F(p + ".h.i.s.4.m", c.harmonic[i].ind.e.mode);
        F(p + ".h.i.s.4.l", c.harmonic[i].ind.e.level);
    }
#undef A
#undef F
}
}

cJSON* editor_snapshot(Configure& config) {
    cJSON* root = cJSON_CreateObject();
    Fields fields(root, nullptr);
    visit(fields, config);
    return root;
}

bool editor_apply(Configure& config, const cJSON* document) {
    if (!cJSON_IsObject(document)) return false;
    Fields fields(nullptr, document);
    visit(fields, config);
    return fields.valid;
}
