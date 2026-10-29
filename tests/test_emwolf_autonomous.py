from __future__ import annotations
import json
import socket
import struct
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch
from wolfeye.services.emwolf_protocol import *
from wolfeye.services.emwolf_run import RunCache, ReceiptLease, EVENT, STATUS, EVENT_LIMIT
from wolfeye.services.emwolf_report import EmWolfRunReport

class AutonomousTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/"board"
        self.project=Project(scenarios=[Scenario(name="one",end_type="TIME",end_value=1)])

    def cache(self):
        return RunCache.create(self.directory,123,asdict(self.project),"2026-10-25T09:00:00+03:30")

    def client(self,cache=None):
        self.logs=[];self.events=[];self.states=[]
        c=EmWolfConnection(self.logs.append,lambda *_a:None,lambda _s:None,
            autonomous_enabled=True,on_run_state=self.states.append,on_run_event=self.events.append,cache_dir=Path(self.temp.name))
        c._socket=Mock();c._cache_directory=self.directory;c._run_cache=cache
        return c

    def frames(self,c):
        return [frame for call in c._socket.sendall.call_args_list for frame in FrameDecoder().feed(call.args[0])]

    def test_cache_resumes_and_rejects_conflicting_replays(self):
        cache=self.cache();raw=EVENT.pack(1,4,0,1,1,(1<<40)+12345)
        cache.append(raw);cache.append(raw)
        self.assertEqual(len(cache.events),1)
        before=cache.events_path.read_bytes()
        with self.assertRaises(ValueError):cache.append(EVENT.pack(1,4,0,1,1,2))
        self.assertEqual(cache.events_path.read_bytes(),before)
        restored=RunCache.load_active(self.directory)
        self.assertEqual(restored.events[0]["time_us"],(1<<40)+12345)

    def test_partial_pc_write_keeps_verified_prefix_and_tail_backup(self):
        cache=self.cache();cache.append(EVENT.pack(1,1,0,0,0,100))
        with cache.events_path.open("ab") as target:target.write(b"part")
        restored=RunCache.load_active(self.directory)
        self.assertEqual(len(restored.events),1)
        self.assertEqual(restored.events_path.with_suffix(".partial").read_bytes(),b"part")
        self.assertEqual(restored.events_path.stat().st_size,21)

    def test_full_receipt_waits_for_every_event_and_disk_commit(self):
        cache=self.cache();c=self.client(cache)
        c._handle_run_frame(EW_RUN_STATUS,STATUS.pack(123,4,2,2,2,1))
        self.assertNotIn(EW_RUN_RECEIVED,[kind for kind,_ in self.frames(c)])
        c._handle_run_frame(EW_RUN_DATA,struct.pack("<QIH",123,1,1)+EVENT.pack(1,1,0,0,0,100))
        self.assertNotIn(EW_RUN_RECEIVED,[kind for kind,_ in self.frames(c)])
        with patch.object(cache,"append",side_effect=OSError("PC disk full")):
            with self.assertRaises(OSError):c._handle_run_frame(EW_RUN_DATA,struct.pack("<QIH",123,2,1)+EVENT.pack(2,5,0,0,0,200))
        self.assertNotIn(EW_RUN_RECEIVED,[kind for kind,_ in self.frames(c)])
        c._handle_run_frame(EW_RUN_DATA,struct.pack("<QIH",123,2,1)+EVENT.pack(2,5,0,0,0,200))
        self.assertIn((EW_RUN_RECEIVED,struct.pack("<QI",123,2)),self.frames(c))
        restored=RunCache.load_active(self.directory)
        self.assertEqual(len(restored.events),2)
        c._handle_run_frame(EW_RUN_STATUS,STATUS.pack(123,4,3,2,2,1))
        self.assertTrue(RunCache.load_active(self.directory).meta["collected"])
        c._handle_run_frame(EW_RUN_DATA,struct.pack("<QIH",123,1,2)+EVENT.pack(1,1,0,0,0,100)+EVENT.pack(2,5,0,0,0,200))
        self.assertEqual(len(self.events),2)

    def test_detach_does_not_stop_and_explicit_stop_has_run_id(self):
        c=self.client(self.cache());c.stop_outputs()
        self.assertEqual(self.frames(c),[(EW_RUN_STOP,struct.pack("<Q",123))])
        c._socket.sendall.reset_mock();c.disconnect()
        c._socket.sendall.assert_not_called();c._socket.shutdown.assert_called_once()

    def test_resending_upload_uses_same_run_id_and_identical_payload(self):
        c=self.client();c.send_project(self.project);c.send_project(self.project)
        frames=self.frames(c)
        self.assertEqual(frames[0],frames[1]);self.assertEqual(frames[0][0],EW_RUN_START)
        self.assertEqual(frames[0][1][8:],self.project.build_payload())
        other=Project(scenarios=[Scenario(name="other",end_type="TIME",end_value=2)])
        with self.assertRaises(ValueError):c.send_project(other)
        self.assertEqual(len(self.frames(c)),2)

    def test_timeout_in_independent_mode_never_sends_stop(self):
        clock=[0.0];sock=Mock();logs=[]
        def recv(_n):clock[0]+=5;raise socket.timeout()
        sock.recv.side_effect=recv
        c=EmWolfConnection(logs.append,lambda *_a:None,lambda _s:None,autonomous_enabled=True,cache_dir=Path(self.temp.name))
        with patch("socket.create_connection",return_value=sock),patch("wolfeye.services.emwolf_protocol.time.monotonic",side_effect=lambda:clock[0]),patch("wolfeye.services.emwolf_protocol.select.select",return_value=([],[],[])):
            c._run("127.0.0.1",666)
        frames=[frame for call in sock.sendall.call_args_list for frame in FrameDecoder().feed(call.args[0])]
        self.assertFalse(any(kind in (EW_STOP,EW_RUN_STOP,EW_RUN_START) for kind,_ in frames))
        self.assertTrue(any("autonomous execution" in message for message in logs))
        sock.close.assert_called_once()

    def test_status_from_previous_run_cannot_replace_current_receipt(self):
        c=self.client(self.cache())
        c._run_snapshot=dict(id=123,state=2)
        c._handle_run_frame(EW_RUN_STATUS,STATUS.pack(999,4,3,1,1,1))
        self.assertEqual(c._run_cache.id,123)
        self.assertEqual(c._run_snapshot,dict(id=123,state=2))
        self.assertEqual(self.states,[])
        self.assertEqual(self.frames(c),[])

    def test_unindexed_legacy_result_does_not_enter_autonomous_report(self):
        sock=Mock();sock.recv.side_effect=[build_frame(EW_RESULT,struct.pack("<I",1|(1<<3)|(12345<<4))),b""]
        measurements=[];trips=[]
        c=EmWolfConnection(lambda _s:None,lambda *a:measurements.append(a),lambda _s:None,
            lambda *a:trips.append(a),autonomous_enabled=True,cache_dir=Path(self.temp.name))
        with patch("socket.create_connection",return_value=sock):c._run("127.0.0.1",666)
        self.assertEqual(measurements,[]);self.assertEqual(trips,[])

    def test_receipt_lock_is_exclusive_and_released(self):
        lease=ReceiptLease(self.directory)
        try:
            with self.assertRaises(OSError):ReceiptLease(self.directory)
        finally:lease.close()
        ReceiptLease(self.directory).close()

    def test_event_bounds_and_oversized_frame_resynchronization(self):
        c=self.client(self.cache())
        with self.assertRaises(ValueError):c._handle_run_frame(EW_RUN_DATA,struct.pack("<QIH",123,1,65))
        with self.assertRaises(ValueError):c._handle_run_frame(EW_RUN_STATUS,STATUS.pack(123,4,2,EVENT_LIMIT+1,0,1))
        decoder=FrameDecoder();valid=build_frame(PING,b"x")
        self.assertEqual(list(decoder.feed(b"A$\xff\xff\x00"+valid)),[(PING,b"x")])

    def test_wire_project_reconstruction_preserves_all_existing_projects(self):
        root=Path(__file__).resolve().parents[1]
        files=list((root/"fc22s_fault_scenarios_DI1_Close_DI2_Open").glob("*.json"))+list((root/"fc22ar_3shot_fault_scenarios_DI1_Open_DI2_Close").glob("*.json"))
        self.assertEqual(len(files),8)
        for path in files:
            original=load_project(path).build_payload()
            self.assertEqual(project_from_wire(original).build_payload(),original)

    def test_report_uses_explicit_stage_and_full_timestamp(self):
        project=Project(scenarios=[Scenario(end_type="TIME"),Scenario(end_type="DI_TOGGLE",digital_input=1),Scenario(end_type="DI_TOGGLE",digital_input=2)])
        project.device.model="FC22AR"
        report=EmWolfRunReport.begin(project)
        report.record_board_event(dict(kind=1,scenario=2,input_id=0,value=False,time_us=0))
        elapsed=(1<<40)+987
        index=report.record_board_event(dict(kind=4,scenario=1,input_id=1,value=True,time_us=elapsed))
        self.assertEqual(index,1);self.assertEqual(report.executions[1].trip_time_us,elapsed)
        report.record_board_event(dict(kind=5,scenario=0,input_id=0,value=False,time_us=1000))
        self.assertEqual(report.executions[0].state,"COMPLETED")

    def test_manual_receive_only_queries_without_reset_or_upload(self):
        cache=self.cache();c=self.client(cache)
        c._fetch_pending_until=123.0
        c.request_results()
        self.assertEqual(self.frames(c),[(EW_RUN_QUERY,struct.pack("<Q",123))])
        self.assertIs(c._run_cache,cache)
        self.assertEqual(c._fetch_pending_until,123.0)
        self.assertEqual(cache.events,[])

    def test_export_results_preserves_full_timestamps_and_receipt_state(self):
        cache=self.cache();c=self.client(cache)
        stamp=(1<<48)+987
        cache.append(EVENT.pack(1,4,0,1,1,stamp))
        c._run_snapshot=dict(id=123,state=4,count=2)
        output=Path(self.temp.name)/"results.json"
        c.export_results(output)
        data=json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["run_id"],"000000000000007b")
        self.assertEqual(data["events"][0]["time_us"],stamp)
        self.assertEqual(data["received_events"],1);self.assertEqual(data["expected_events"],2)
        self.assertFalse(data["results_received"])
        self.assertEqual(data["project"],asdict(self.project))
        cache.append(EVENT.pack(2,5,0,0,0,stamp+1));cache.status(4,True)
        c.export_results(output)
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["results_received"])
        self.assertEqual(self.frames(c),[])

    def test_export_failure_keeps_previous_file_and_receipt(self):
        cache=self.cache();c=self.client(cache)
        before=cache.meta_path.read_bytes();output=Path(self.temp.name)/"results.json";output.write_text("previous")
        with patch("wolfeye.services.emwolf_protocol.os.replace",side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):c.export_results(output)
        self.assertEqual(output.read_text(),"previous")
        self.assertEqual(cache.meta_path.read_bytes(),before)
        self.assertFalse(list(output.parent.glob(".results.json.*.tmp")))
        self.assertEqual(self.frames(c),[])

    def test_export_cannot_overwrite_protected_pc_receipts(self):
        cache=self.cache();c=self.client(cache);before=cache.meta_path.read_bytes()
        with self.assertRaises(ValueError):c.export_results(cache.meta_path)
        self.assertEqual(cache.meta_path.read_bytes(),before)
        self.assertEqual(self.frames(c),[])
