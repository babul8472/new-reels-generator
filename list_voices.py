import riva.client
from riva.client.proto.riva_tts_pb2 import RivaSynthesisConfigRequest

auth = riva.client.Auth(
    uri="grpc.nvcf.nvidia.com:443",
    use_ssl=True,
    metadata_args=[
        ["function-id", "877104f7-e885-42b9-8de8-f6e4c6303969"],
        ["authorization", "Bearer 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"],
    ],
)

try:
    service = riva.client.SpeechSynthesisService(auth)
    req = RivaSynthesisConfigRequest()
    config = service.stub.GetRivaSynthesisConfig(req)
    
    with open("voices_output.txt", "w", encoding="utf-8") as f:
        f.write(str(config))
    print("Successfully wrote config to voices_output.txt")
except Exception as e:
    print("Error:", e)
