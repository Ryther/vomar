import cbor2,pytest
from vomar_updater.adapters.smp import decode_cbor,decode_identity,packet,parse_packet

@pytest.mark.parametrize('raw',[b'\xa2\x61a\x01\x61a\x02',cbor2.dumps({'a':1.5}),cbor2.dumps({'a':None}),cbor2.dumps({'a':2**40}),cbor2.dumps({'a':{'b':{'c':{'d':1}}}})])
def test_authority_cbor_rejects_ambiguous_scalars(raw):
    with pytest.raises(ValueError):decode_cbor(raw)

def test_header_sequence_group_and_opcode_are_bound():
    raw=packet(1,0x8040,1,7,{'rc':8})
    assert parse_packet(raw,0,0x8040,1,7)=={'rc':8}
    for expected in [(0,0x8040,1,8),(0,0x8041,1,7),(2,0x8040,1,7)]:
        with pytest.raises(ValueError):parse_packet(raw,*expected)

def test_identity_has_exact_scalar_types():
    x={'protocol':2,'model':'VIMAR30805','layout':2,'uid':[1,2],'loader':{'kind':'common-code44k-anchor-v1','digest':bytes(32),'anchor_sha256':bytes(32)}}
    assert decode_identity(x,1).uid==('00000001','00000002')
    x['uid']=[True,2]
    with pytest.raises(ValueError):decode_identity(x,1)


def test_server_upload_prefix_resume_is_bounded_and_reported():
    import asyncio
    from vomar_updater.adapters.smp import BleakSmp
    async def scenario():
        b=BleakSmp();seen=[];acks=[]
        async def request(op,group,command,payload):
            seen.append(payload['off']);return {'off':256 if payload['off']==0 else min(payload['off']+128,512)}
        async def progress(offset):acks.append(offset)
        b.request=request;await b.upload(bytes(512),progress)
        assert seen==[0,256,384] and acks==[256,384,512]
    asyncio.run(scenario())
